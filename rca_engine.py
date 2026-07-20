import psutil
import time


def analyze_cpu_cause():

    processes = []

    # Garder les MÊMES objets Process entre le "warm-up" et la vraie mesure.
    # psutil.process_iter() recrée de nouveaux objets à chaque appel, donc
    # appeler cpu_percent() deux fois sur deux itérations différentes ne
    # priming rien : chaque objet ne voit qu'un seul appel, et cpu_percent()
    # retourne 0.0 sur le tout premier appel d'un objet donné.
    proc_list = []

    for process in psutil.process_iter(['pid', 'name']):

        try:
            process.cpu_percent()  # premier appel = amorçage (retourne 0.0, normal)
            proc_list.append(process)

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


    # Attendre pour laisser le temps aux compteurs de s'accumuler
    time.sleep(1)


    # Deuxième mesure réelle, sur les MÊMES objets Process
    for process in proc_list:

        try:

            cpu = process.cpu_percent()  # deuxième appel = vraie valeur


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

