import psutil
import time
import os
import csv
import json
import joblib
import pandas as pd

from rca_engine import analyze_cpu_cause
from webhook import trigger_remediation


COUNTER_LIMIT = 10  # consecutive anomalous readings required before firing an incident
COOLDOWN_AFTER_INCIDENT = 30  # seconds to wait before resuming detection after an incident

LOG_FILE = "cpu_metrics_log.csv"
LOG_FIELDS = [
    "timestamp",
    "cpu_percent",
    "mem_percent",
    "load_avg_1min",
    "counter",
    "is_incident",
]

MODEL_FILE = "iso_forest_cpu.joblib"
SCALER_FILE = "cpu_scaler.joblib"
FEATURES_ORDER = ["cpu_percent", "mem_percent", "load_avg_1min"]

counter = 0


def load_model():
    """Load the trained Isolation Forest + its scaler. Both must exist
    (produced by retrain_on_ec2.py) before this engine can run."""
    if not os.path.exists(MODEL_FILE) or not os.path.exists(SCALER_FILE):
        raise FileNotFoundError(
            f"Missing {MODEL_FILE} or {SCALER_FILE}. Run retrain_on_ec2.py first."
        )
    model = joblib.load(MODEL_FILE)
    scaler = joblib.load(SCALER_FILE)
    return model, scaler


def is_anomalous(model, scaler, cpu, mem, load_avg):
    """Ask the trained model whether this single reading looks abnormal.
    Returns True/False. Replaces the old `cpu > THRESHOLD` rule."""
    row = pd.DataFrame([[cpu, mem, load_avg]], columns=FEATURES_ORDER)
    scaled = scaler.transform(row)
    prediction = model.predict(scaled)  # -1 = anomaly, 1 = normal
    return prediction[0] == -1


def init_log_file():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            writer.writeheader()


def log_reading(cpu, mem, load_avg, counter_value, is_incident):
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writerow(
            {
                "timestamp": time.time(),
                "cpu_percent": cpu,
                "mem_percent": mem,
                "load_avg_1min": load_avg,
                "counter": counter_value,
                "is_incident": is_incident,
            }
        )


def collect_reading():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    load_avg = os.getloadavg()[0]
    return cpu, mem, load_avg


init_log_file()
model, scaler = load_model()

print(f"🤖 Loaded ML model ({MODEL_FILE}) — replacing fixed threshold with learned anomaly detection")
print(f"📊 Logging every reading to {LOG_FILE} (running continuously)")

while True:

    cpu, mem, load_avg = collect_reading()

    anomaly = is_anomalous(model, scaler, cpu, mem, load_avg)

    event = {
        "metric": "cpu",
        "value": cpu,
        "mem_percent": mem,
        "load_avg_1min": load_avg,
        "ml_anomaly": anomaly,
        "timestamp": time.time(),
    }

    print(event)

    # Détection anomalie (ML-based instead of fixed threshold)
    if anomaly:
        counter += 1
    else:
        counter = 0

    is_incident = counter >= COUNTER_LIMIT

    log_reading(cpu, mem, load_avg, counter, is_incident)

    if is_incident:

        incident = {
            "type": "CPU_OVERLOAD",
            "priority": "HIGH",
        }

        print("\n🚨 INCIDENT DETECTED (ML)")
        print(json.dumps(incident, indent=2))

        print("\n🔎 Starting RCA...")
        causes = analyze_cpu_cause()

        if causes:
            root_cause = causes[0]
            print("Root Cause:", root_cause)

            if root_cause["name"] == "stress":
                incident["action"] = "kill_process"
            else:
                incident["action"] = "restart_service"

        print("\nDecision:")
        print(incident)

        print("\n📡 Dispatching cpu_alert to GitHub Actions...")
        trigger_remediation("cpu_alert")

        counter = 0
        print(f"\n⏳ Cooling down for {COOLDOWN_AFTER_INCIDENT}s before resuming detection...\n")
        time.sleep(COOLDOWN_AFTER_INCIDENT)
