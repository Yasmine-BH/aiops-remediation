import subprocess
import requests
import time
import os
import csv
import json

from webhook import trigger_remediation


CHECK_INTERVAL = 5  # seconds between checks

incident_active = False  # True while an ongoing outage hasn't recovered yet

LOG_FILE = "service_metrics_log.csv"
LOG_FIELDS = [
    "timestamp",
    "service",
    "status",
    "responding",
    "response_time_ms",
    "is_incident",
]


def init_log_file():
    """Create the CSV file with a header row if it doesn't exist yet."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            writer.writeheader()


def log_reading(event, is_incident):
    """Append a single reading to the CSV log. Called on every check,
    not just when an incident fires — you need the normal/healthy
    baseline logged too, not just the failures."""
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writerow(
            {
                "timestamp": event["timestamp"],
                "service": event["service"],
                "status": event["status"],
                "responding": event["responding"],
                "response_time_ms": event["response_time_ms"],
                "is_incident": is_incident,
            }
        )


INCIDENTS_LOG = "incidents_log.jsonl"  # shared with aiops_engine.py, read by the dashboard


def log_incident_story(record):
    with open(INCIDENTS_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")


def check_apache():

    status = subprocess.run(
        ["systemctl", "is-active", "apache2"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    responding = False
    response_time_ms = None

    try:
        start = time.time()
        response = requests.get("http://localhost", timeout=3)
        response_time_ms = round((time.time() - start) * 1000, 2)
        responding = response.status_code == 200

    except Exception:
        responding = False

    return {
        "service": "apache2",
        "status": status,
        "responding": responding,
        "response_time_ms": response_time_ms,
        "timestamp": time.time(),
    }


init_log_file()

print(f"📊 Logging every check to {LOG_FILE} (running continuously)")

while True:

    event = check_apache()

    print(event)

    is_incident = event["status"] != "active" or event["responding"] is False

    # Log every reading, whether healthy or an incident
    log_reading(event, is_incident)

    if not is_incident:
        # A healthy check means any ongoing outage has genuinely
        # recovered — clear the flag so the next failure is treated
        # as a fresh, new incident rather than a continuation.
        incident_active = False

    if is_incident and not incident_active:

        incident_active = True
        incident_time = time.time()

        incident = {
            "type": "SERVICE_DOWN",
            "priority": "CRITICAL",
            "action": "restart_apache",
        }

        print("\n🚨 INCIDENT DETECTED")
        print(json.dumps(incident, indent=2))

        # AUTOMATISATION (via GitHub Actions -> Ansible service_fix.yml)
        print("\n📡 Dispatching service_alert to GitHub Actions...")
        dispatch_status = trigger_remediation("service_alert")
        dispatch_success = dispatch_status == 204

        print("\n✅ Remediation dispatched" if dispatch_success else "\n❌ Remediation dispatch failed")

        log_incident_story({
            "timestamp": incident_time,
            "source": "service",
            "type": incident["type"],
            "priority": incident["priority"],
            "trigger_values": {
                "status": event["status"],
                "responding": event["responding"],
                "response_time_ms": event["response_time_ms"],
            },
            "ml_detected": False,  # this side is rule-based, not ML — the dashboard should say so honestly
            "root_cause": "Apache inactive or not responding to HTTP requests"
                if event["status"] != "active" else "Apache active but not responding (possible hang)",
            "action_taken": incident["action"],
            "dispatch_success": dispatch_success,
            "dispatch_status_code": dispatch_status,
        })

        print("\n✅ Incident recorded. Will not re-dispatch until service recovers first.\n")

    elif is_incident and incident_active:
        print("(ongoing outage, already handled — waiting for recovery)")

    time.sleep(CHECK_INTERVAL)
