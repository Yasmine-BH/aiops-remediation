import psutil
import time


def analyze_cpu_cause(sample_interval=0.3):
    """
    sample_interval: how long to wait between the priming call and the
    real measurement, in seconds.

    This was originally 1.0s. That's the psutil-recommended interval for
    a *stable* reading, but it also means RCA samples up to ~1-2 seconds
    after the incident actually triggered (the main loop's own 1s
    cpu_percent() call, plus this function's own delay). For sustained
    load (e.g. a stress test), that gap doesn't matter — the culprit is
    still there a second later. But for brief, bursty causes (e.g. a
    scheduled OS task like apt-daily spawning short-lived processes),
    the real culprit can have already exited by the time RCA looks,
    leaving an innocent long-running process looking like the cause.

    Shortening this to 0.3s trades a bit of measurement stability for
    a much better chance of still catching bursty, short-lived causes
    before they're gone. Sustained-load detection (validated against
    real stress-ng tests) is unaffected either way.
    """

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

    # Attendre pour laisser le temps aux compteurs de s'accumuler.
    # Raccourci pour rester au plus près du moment réel de l'incident.
    time.sleep(sample_interval)

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
