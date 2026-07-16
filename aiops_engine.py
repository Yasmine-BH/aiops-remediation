import psutil
import time
import json

from rca_engine import analyze_cpu_cause
from webhook import trigger_remediation

# Seuil CPU (%)
THRESHOLD = 90

# Nombre de mesures consécutives au-dessus du seuil
counter = 0


def detect_incident(cpu):
    global counter

    if cpu > THRESHOLD:
        counter += 1
    else:
        counter = 0

    if counter >= 5:
        incident = {
            "type": "CPU_OVERLOAD",
            "priority": "HIGH"
        }

        print("\n🚨 INCIDENT DETECTED")
        print(json.dumps(incident, indent=4))

        return True

    return False


def execute_rca():
    print("\n🔎 Starting RCA...")

    causes = analyze_cpu_cause()

    print("Root Cause:")
    print(causes)

    return causes


def make_decision(causes):

    if len(causes) == 0:
        return {
            "type": "CPU_OVERLOAD",
            "priority": "HIGH",
            "action": "restart_service"
        }

    top_process = causes[0]

    if top_process["name"] == "stress":
        action = "kill_process"
    else:
        action = "restart_service"

    decision = {
        "type": "CPU_OVERLOAD",
        "priority": "HIGH",
        "action": action
    }

    return decision


def launch_remediation():

    print("\n🚀 Sending incident to GitHub Actions...")

    status = trigger_remediation("cpu_alert")

    if status == 204:
        print("✅ GitHub Actions successfully triggered")
    else:
        print("❌ Failed to trigger GitHub Actions")


while True:

    cpu = psutil.cpu_percent(interval=1)

    event = {
        "metric": "cpu",
        "value": cpu,
        "timestamp": time.time()
    }

    print(event)

    if detect_incident(cpu):

        causes = execute_rca()

        decision = make_decision(causes)

        print("\nDecision:")
        print(json.dumps(decision, indent=4))

        launch_remediation()

        counter = 0

    time.sleep(1)

