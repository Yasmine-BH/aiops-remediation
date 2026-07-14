import psutil
import time


def analyze_cpu_cause():

    processes = []


    # Premier appel pour initialiser les compteurs
    for process in psutil.process_iter():

        try:
            process.cpu_percent()

        except:
            pass


    # Attendre pour mesurer
    time.sleep(1)



    # Deuxième mesure réelle
    for process in psutil.process_iter(
        ['pid', 'name']
    ):

        try:

            cpu = process.cpu_percent()


            processes.append(
                {
                    "pid": process.pid,
                    "name": process.name(),
                    "cpu": cpu
                }
            )


        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied
        ):
            pass



    processes = sorted(
        processes,
        key=lambda x: x["cpu"],
        reverse=True
    )


    return processes[:5]



if __name__ == "__main__":

    print("===== RCA CPU ANALYSIS =====")


    result = analyze_cpu_cause()


    for p in result:

        print(
            f"PID:{p['pid']} "
            f"NAME:{p['name']} "
            f"CPU:{p['cpu']}%"
        )
