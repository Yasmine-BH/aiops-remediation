import psutil
import time
import subprocess
import json

from rca_engine import analyze_cpu_cause
from webhook import trigger_github_action


THRESHOLD = 90

counter = 0





while True:


    cpu = psutil.cpu_percent(interval=1)


    event = {

        "metric": "cpu",

        "value": cpu,

        "timestamp": time.time()

    }


    print(event)



    # Détection anomalie

    if cpu > THRESHOLD:

        counter += 1


    else:

        counter = 0




    # Incident confirmé

    if counter >= 10:


        incident = {

            "type": "CPU_OVERLOAD",

            "priority": "HIGH"

        }


        print("\n🚨 INCIDENT DETECTED")

        print(
            json.dumps(
                incident,
                indent=2
            )
        )



        # RCA

        print("\n🔎 Starting RCA...")


        causes = analyze_cpu_cause()


        if causes:


            root_cause = causes[0]


            print(
                "Root Cause:",
                root_cause
            )



            # Décision

            if root_cause["name"] == "stress":

                incident["action"] = "kill_process"


            else:

                incident["action"] = "restart_service"



        print("\nDecision:")

        print(incident)



        # Remédiation automatique (via GitHub Actions -> AWS Auto Scaling)

        print("\n📡 Dispatching cpu_alert to GitHub Actions...")

        trigger_github_action("cpu_alert")


        break
