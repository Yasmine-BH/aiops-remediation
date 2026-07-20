import subprocess
import requests
import time
import json

from webhook import trigger_github_action



def check_apache():


    status = subprocess.run(

        [
            "systemctl",
            "is-active",
            "apache2"
        ],

        capture_output=True,

        text=True

    ).stdout.strip()



    try:

        response = requests.get(
            "http://localhost",
            timeout=3
        )

        responding = response.status_code == 200


    except:

        responding = False



    return {

        "service":"apache2",

        "status":status,

        "responding":responding,

        "timestamp":time.time()

    }



while True:


    event = check_apache()


    print(event)



    if (

        event["status"] != "active"

        or

        event["responding"] == False

    ):


        incident = {


            "type":
            "SERVICE_DOWN",


            "priority":
            "CRITICAL",


            "action":
            "restart_apache"


        }



        print("\n🚨 INCIDENT DETECTED")

        print(

            json.dumps(
                incident,
                indent=2
            )

        )



        # AUTOMATISATION (via GitHub Actions -> Ansible service_fix.yml)

        print("\n📡 Dispatching service_alert to GitHub Actions...")

        trigger_github_action("service_alert")



        print("\n✅ Remediation dispatched")


        break



    time.sleep(5)
