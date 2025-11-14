
# ================================================================
# File: tasks
# kinda like a cron setup
# ================================================================
import threading
import time

def __interval_task():
    count = 0
    while True:
        # reset every 24hr
        if (count := count + 1) >= 86400:
            count = 0
        try:
            # 10 minute
            if count % 600:
                pass
        except:
            pass
        time.sleep(1)

__interval_thread_started = False

def start_interval_task():
    global __interval_thread_started
    if not __interval_thread_started:
        threading.Thread(target=__interval_task, daemon=True).start()
        __interval_thread_started = True

start_interval_task()
