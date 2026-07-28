from flask import Flask, jsonify, render_template
import pandas as pd
import os
import time


app = Flask(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CPU_CSV = os.path.join(BASE_DIR, "cpu_metrics_log.csv")
SERVICE_CSV = os.path.join(BASE_DIR, "service_metrics_log.csv")

MODEL_FILE = os.path.join(BASE_DIR, "iso_forest_cpu.joblib")
RETRAIN_LOG = os.path.join(BASE_DIR, "retrain.log")


MAX_POINTS = 200
MAX_LOG_LINES = 25



def safe_read_csv(path, n=MAX_POINTS):

    if not os.path.exists(path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
        return df.tail(n)

    except Exception:
        return pd.DataFrame()



@app.route("/")
def dashboard():

    return render_template("dashboard.html")



@app.route("/api/data")
def api_data():

    cpu_df = safe_read_csv(CPU_CSV)
    service_df = safe_read_csv(SERVICE_CSV)


    cpu_data = {
        "timestamps": [],
        "cpu_percent": [],
        "mem_percent": [],
        "load_avg_1min": []
    }


    latest_cpu = {
        "cpu_percent": None,
        "mem_percent": None,
        "load_avg_1min": None
    }


    incident_log = []

    cpu_incidents = 0



    # -------------------------
    # CPU TELEMETRY
    # -------------------------

    if not cpu_df.empty:


        cpu_data["timestamps"] = cpu_df["timestamp"].tolist()

        cpu_data["cpu_percent"] = (
            cpu_df["cpu_percent"]
            .tolist()
        )

        cpu_data["mem_percent"] = (
            cpu_df["mem_percent"]
            .tolist()
        )

        cpu_data["load_avg_1min"] = (
            cpu_df["load_avg_1min"]
            .tolist()
        )


        last = cpu_df.iloc[-1]


        latest_cpu = {

            "cpu_percent":
                float(last["cpu_percent"]),

            "mem_percent":
                float(last["mem_percent"]),

            "load_avg_1min":
                float(last["load_avg_1min"])
        }



        full_cpu = pd.read_csv(CPU_CSV)


        cpu_incidents = int(
            full_cpu["is_incident"].sum()
        )


        detected = (
            full_cpu[
                full_cpu["is_incident"] == True
            ]
            .tail(MAX_LOG_LINES)
        )


        for _, row in detected[::-1].iterrows():

            incident_log.append({

                "time":
                    time.strftime(
                        "%H:%M:%S",
                        time.gmtime(row["timestamp"])
                    ),

                "type":
                    "HIGH CPU UTILIZATION",

                "detail":
                    f"CPU {row['cpu_percent']:.1f}% | "
                    f"Memory {row['mem_percent']:.1f}%",

                "severity":
                    "critical"
            })




    # -------------------------
    # SERVICE MONITORING
    # -------------------------

    service_status = {

        "status":
            "unknown",

        "responding":
            False,

        "response_time_ms":
            None
    }


    service_incidents = 0



    if not service_df.empty:


        last_service = service_df.iloc[-1]


        service_status = {


            "status":
                last_service["status"],


            "responding":
                bool(last_service["responding"]),


            "response_time_ms":
                float(
                    last_service["response_time_ms"]
                )

        }



        full_service = pd.read_csv(
            SERVICE_CSV
        )


        service_incidents = int(
            full_service["is_incident"].sum()
        )



        detected = (
            full_service[
                full_service["is_incident"] == True
            ]
            .tail(MAX_LOG_LINES)
        )


        for _, row in detected[::-1].iterrows():


            incident_log.append({

                "time":
                    time.strftime(
                        "%H:%M:%S",
                        time.gmtime(row["timestamp"])
                    ),

                "type":
                    "SERVICE FAILURE",

                "detail":
                    f"Status {row['status']}",

                "severity":
                    "warning"

            })



    incident_log.sort(
        key=lambda x:x["time"],
        reverse=True
    )


    # -------------------------
    # ML MODEL INFORMATION
    # -------------------------


    model_info = {


        "algorithm":
            "Isolation Forest",


        "version":
            "v2.1",


        "loaded":
            False,


        "last_update":
            None
    }



    if os.path.exists(MODEL_FILE):

        model_info["loaded"] = True


        model_info["last_update"] = (

            time.strftime(

                "%Y-%m-%d %H:%M:%S UTC",

                time.gmtime(
                    os.path.getmtime(
                        MODEL_FILE
                    )
                )
            )
        )



    # -------------------------
    # RETRAIN INFORMATION
    # -------------------------


    metrics = "No retraining history"


    if os.path.exists(RETRAIN_LOG):

        with open(RETRAIN_LOG) as f:

            lines = f.readlines()


        for line in reversed(lines):

            if (
                "Precision" in line
                and
                "Recall" in line
            ):

                metrics=line.strip()

                break




    # -------------------------
    # SYSTEM HEALTH
    # -------------------------

    health = "HEALTHY"


    if (
        latest_cpu["cpu_percent"]
        and
        latest_cpu["cpu_percent"] > 85
    ):

        health="WARNING"


    if len(incident_log) > 5:

        health="CRITICAL"



    return jsonify({


        "system": {


            "health":
                health,


            "monitoring":
                True,


            "auto_remediation":
                True

        },


        "cpu":
            cpu_data,


        "latest_cpu":
            latest_cpu,


        "cpu_incidents":
            cpu_incidents,


        "service_incidents":
            service_incidents,


        "service":
            service_status,


        "incidents":
            incident_log,


        "model":
            model_info,


        "retraining":
            metrics,


        "server_time":
            time.strftime(
                "%Y-%m-%d %H:%M:%S UTC",
                time.gmtime()
            )

    })




if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )

