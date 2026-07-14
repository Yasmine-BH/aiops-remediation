import psutil
import time
import subprocess
import json

from rca_engine import analyze_cpu_cause


THRESHOLD = 90

counter = 0



def run_ansible():

    print("🚀 Launching Ansible remediation")


    result = subprocess.run(
        [
            "ansible-playbook",
            "playbooks/cpu_fix.yml"
        ],
        capture_output=True,
        text=True
    )


    print(result.stdout)


    if result.returncode == 0:
        print("✅ Remediation completed")

    else:
        print("❌ Remediation failed")





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



        # Remédiation automatique

        run_ansible()


        break
