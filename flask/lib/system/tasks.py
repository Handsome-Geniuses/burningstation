
# ================================================================
# File: tasks
# kinda like a cron setup
# ================================================================
import threading
import time
from lib.automation.jobs import start_passive_job
from lib.meter.meter_manager import METERMANAGER as mm
from lib.system.states import states

def __interval_task():
    count = 0
    while True:
        # reset every 24hr
        if (count := count + 1) >= 86400:
            count = 0
        try:
            # 10 minute
            if not (count % 600):
                pass
            if not (count % 6): 
                # print("refreshing meters")
                fresh,stale,ips = mm.refresh()
                # print(f"ips: {ips}")
                # print(f"fresh: {fresh}, stale: {stale}")
                for ip in fresh: 
                    print(f"fresh ip: {ip}")
                    if states['mode']=='auto':
                        mm.get_meter(ip).setup_custom_display()
                        start_passive_job(ip)
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
