import subprocess
import requests
import time
import os
import csv
import json

from webhook import trigger_remediation


CHECK_INTERVAL = 5  # seconds between checks
COOLDOWN_AFTER_INCIDENT = 30  # seconds to wait before resuming detection after an incident

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

    if is_incident:

        incident = {
            "type": "SERVICE_DOWN",
            "priority": "CRITICAL",
            "action": "restart_apache",
        }

        print("\n🚨 INCIDENT DETECTED")
        print(json.dumps(incident, indent=2))

        # AUTOMATISATION (via GitHub Actions -> Ansible service_fix.yml)
        print("\n📡 Dispatching service_alert to GitHub Actions...")
        trigger_remediation("service_alert")

        print("\n✅ Remediation dispatched")

        # Cool down instead of exiting, so the engine keeps running
        # and keeps collecting data for future ML training.
        print(f"\n⏳ Cooling down for {COOLDOWN_AFTER_INCIDENT}s before resuming detection...\n")
        time.sleep(COOLDOWN_AFTER_INCIDENT)
        continue

    time.sleep(CHECK_INTERVAL)
