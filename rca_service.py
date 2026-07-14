import subprocess



def analyze_service():

    result = subprocess.run(

        [
            "systemctl",
            "status",
            "apache2"
        ],

        capture_output=True,

        text=True

    )


    output = result.stdout + result.stderr



    if "inactive" in output:


        cause = {

            "cause":
            "Apache service stopped",

            "type":
            "SERVICE_FAILURE"

        }


    else:


        cause = {

            "cause":
            "Apache not responding",

            "type":
            "APPLICATION_FAILURE"

        }


    return cause



if __name__ == "__main__":


    print(analyze_service())
