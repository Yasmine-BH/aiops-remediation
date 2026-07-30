# AIOps Remediation

An end-to-end AIOps pipeline that monitors a Linux server, detects anomalies using a machine learning model, performs lightweight root-cause analysis, and triggers automated remediation through GitHub Actions and Ansible — with a self-retraining loop to keep the ML model up to date.

## Overview

The project watches two things in parallel:

1. **CPU / system health** — CPU, memory and load average, analyzed by an **Isolation Forest** anomaly detection model (unsupervised ML) instead of a fixed threshold.
2. **Apache service health** — whether the `apache2` service is active and actually responding to HTTP requests.

When either detector confirms a sustained incident, it:
1. Runs a quick **root cause analysis** (which process is hogging the CPU / why Apache is down) for diagnostics and logging.
2. Dispatches an event to **GitHub Actions** via a `repository_dispatch` webhook.
3. GitHub Actions runs an **Ansible playbook** that performs the actual remediation (e.g. AWS Auto Scaling for CPU overload, restarting Apache for service failures).

A separate loop periodically **stress-tests** the machine to generate labeled incident data, and **retrains** the Isolation Forest model on that data, reloading it into the live detection engine without manual intervention.

```
 ┌──────────────────────┐      ┌──────────────────────┐
 │   aiops_engine.py      │      │ aiops_engine_service.py│
 │  (CPU / ML detection)  │      │  (Apache health check) │
 └──────────┬────────────┘      └──────────┬────────────┘
            │ incident                      │ incident
            ▼                                ▼
     ┌──────────────┐                ┌───────────────┐
     │ rca_engine.py │                │ rca_service.py │
     │ (top CPU procs)│               │ (systemctl status)│
     └──────┬────────┘                └───────┬───────┘
            │                                  │
            └───────────────┬──────────────────┘
                             ▼
                       webhook.py
                (repository_dispatch → GitHub)
                             │
                             ▼
                .github/workflows/*.yml
                             │
                             ▼
                     playbooks/*.yml (Ansible)
                             │
                             ▼
                 scale_out (AWS) / restart_apache
```

```
 ┌────────────────────────────┐
 │ aiops-stress-test.timer      │  4x/day → generates a controlled CPU spike
 └──────────────┬──────────────┘
                ▼
       aiops_engine.py logs it → cpu_metrics_log.csv
                │
                ▼
       retrain_and_reload.sh (scheduled)
                │
                ├─ retrain_on_ec2.py → retrains Isolation Forest
                │        on the latest logged data
                │
                └─ systemctl restart aiops-cpu-engine
                         (reloads the freshly trained model)
```

## Repository structure

| File | Role |
|---|---|
| `aiops_engine.py` | Main CPU detection loop. Loads the trained Isolation Forest + scaler, samples CPU/mem/load every second via `psutil`, flags anomalies, and fires an incident after `COUNTER_LIMIT` consecutive anomalous readings. Logs every reading to `cpu_metrics_log.csv`. |
| `aiops_engine_service.py` | Apache health-check loop. Checks `systemctl is-active apache2` and whether `http://localhost` actually responds. Fires a `SERVICE_DOWN` incident if either check fails. Logs to `service_metrics_log.csv`. |
| `rca_engine.py` | Root cause analysis for CPU incidents — lists the top 5 processes by CPU usage at the time of the incident (diagnostics only, does not affect the remediation decision). |
| `rca_service.py` | Root cause analysis for Apache incidents — distinguishes "service stopped" from "process running but not responding" via `systemctl status`. |
| `webhook.py` | Sends a `repository_dispatch` event to the GitHub API (`cpu_alert` / `service_alert`), authenticated with a `GITHUB_TOKEN` environment variable. This is what actually triggers the remediation workflow. |
| `dashboard.py` | Visualization dashboard for the collected metrics, incidents, and current model status. |
| `retrain_on_ec2.py` | Retraining script. Reconstructs a corrected ground truth from `cpu_metrics_log.csv` (padding around each detected spike to capture ramp-up/peak/recovery, not just the trigger row), trains a new Isolation Forest **on normal data only**, validates it (precision/recall against the ground truth), and overwrites `iso_forest_cpu.joblib` / `cpu_scaler.joblib`. |
| `retrain_and_reload.sh` | Orchestration script: runs `retrain_on_ec2.py`, then restarts the `aiops-cpu-engine` service so the freshly trained model is actually loaded (the engine only loads the model once, at startup). Uses `set -e` so a failed retrain never triggers a restart with a stale/missing model. |
| `iso_forest_cpu.joblib` | Serialized trained Isolation Forest model. |
| `cpu_scaler.joblib` | Serialized `StandardScaler` used to normalize `cpu_percent` / `mem_percent` / `load_avg_1min` before scoring. |
| `cpu_metrics_log.csv` | Every CPU/mem/load reading collected by `aiops_engine.py` (generated at runtime). |
| `service_metrics_log.csv` | Every Apache health check collected by `aiops_engine_service.py` (generated at runtime). |
| `incidents_log.jsonl` | Structured, one-JSON-object-per-line log of detected incidents (generated at runtime). |
| `aiops-dashboard.service` | systemd unit that runs `dashboard.py` as a persistent background service. |
| `aiops-stress-test.service` / `.timer` | systemd service + timer that runs a controlled stress test 4 times a day (06:00, 12:00, 18:00, 22:00) to generate labeled incident data for retraining. |
| `.github/workflows/` | GitHub Actions workflows triggered by the `repository_dispatch` events sent from `webhook.py`. |
| `playbooks/` | Ansible playbooks that perform the actual remediation (AWS scale-out, Apache restart). |
| `.gitignore` | Standard Git exclusions. |

## How detection works

### CPU (ML-based)

- Every second, `aiops_engine.py` samples `cpu_percent`, `mem_percent`, and `load_avg_1min`.
- The reading is scaled and scored by the Isolation Forest (`-1` = anomaly, `1` = normal).
- **Safety floor:** readings below 15% CPU are never flagged as anomalous, regardless of the model's output — this protects against an overfit/oversensitive model firing false incidents (and false AWS remediation calls) on completely idle load.
- An incident only fires after `COUNTER_LIMIT` (10) **consecutive** anomalous readings, to avoid reacting to a single transient spike.
- After firing, the engine cools down for `COOLDOWN_AFTER_INCIDENT` (30s) before resuming detection, to avoid firing repeated incidents while the remediation is still taking effect.

### Apache (rule-based)

- Every `CHECK_INTERVAL` (5s), checks both `systemctl is-active apache2` and an actual HTTP request to `localhost`.
- Any failure on either check is treated as an incident (a service can be "active" per systemd but still fail to respond).

## Model retraining

The Isolation Forest is retrained periodically (via `retrain_and_reload.sh`) rather than being static:

1. `aiops-stress-test.timer` generates controlled CPU spikes 4x/day, which get logged as normal detection data.
2. `retrain_on_ec2.py` reconstructs a more accurate ground truth than the live `is_incident` flag — it flags CPU > 60% or load recovering to 3x its rolling baseline, then pads ±5 readings around each detected spike to also capture the ramp-up and recovery phases.
3. The model is trained **only on rows judged normal**, then validated (precision/recall) against the full dataset including incidents.
4. The new `.joblib` files overwrite the old ones, and the detection engine is restarted to load them.

This keeps the model aligned with the server's evolving baseline behavior instead of relying on a one-time fixed threshold.

## Remediation

| Incident type | Trigger | Action |
|---|---|---|
| `CPU_OVERLOAD` | Sustained anomalous CPU/mem/load | `scale_out` — AWS Auto Scaling, via Ansible |
| `SERVICE_DOWN` | Apache inactive or not responding | `restart_apache`, via Ansible |

Remediation is not executed directly on the monitored machine. Instead, `webhook.py` dispatches a `repository_dispatch` event to this repository's GitHub Actions, which runs the corresponding Ansible playbook. This keeps AWS/Ansible credentials off the monitored host and gives an auditable execution history in GitHub Actions.

## Requirements

- Python 3, with: `psutil`, `pandas`, `numpy`, `scikit-learn`, `joblib`, `requests`
- A `GITHUB_TOKEN` environment variable with permission to trigger `repository_dispatch` on this repository
- `systemd` (for the `.service` / `.timer` units)
- Ansible (for the playbooks executed by GitHub Actions)

## Running locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install psutil pandas numpy scikit-learn joblib requests

# Train an initial model (requires some cpu_metrics_log.csv data to exist)
python3 retrain_on_ec2.py

# Start detection
export GITHUB_TOKEN=your_token_here
python3 aiops_engine.py          # CPU detection
python3 aiops_engine_service.py  # Apache detection
```
