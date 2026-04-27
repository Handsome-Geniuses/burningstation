
# ================================================================
# File: tasks
# kinda like a cron setup
# ================================================================
import threading
import time
from lib.automation.jobs import start_passive_job
from lib.meter.meter_manager import METERMANAGER as mm
from lib.system.states import states
from lib.system.station import load_R_to_M, load_M_to_L, load_L, load_M, load_R

def __temporary_overnight_runner():
    from lib.automation.jobs import start_job
    fresh,stale,ips = mm.refresh()

    ips = mm.list_meters()

    if len(ips) == 0: return
    meterip = ips[0]
    meter = mm.get_meter(meterip)

    modules = meter.module_info
    has_nfc = "KIOSK_NFC" in modules
    has_modem = "MK7_XE910" in modules
    has_printer = "PRINTER" in modules
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_screen_test = True 

    kwargs = {
        "nfc": 1 if has_nfc else 0,
        "modem": 1 if has_modem else 0 ,
        "printer": 1 if has_printer else 0,
        "coin shutter": 1 if has_coin_shutter else 0,
        "screen test": 1 if has_screen_test else 0,
        "numBurnCycles": 5,
        "numBurnDelay": 10
    }

    start_job(meterip, "cycle_all", kwargs, verbose=True)


def __temporary_overnight_runner():
    ips = mm.list_meters()
    if len(ips) == 0: return
    meterip = ips[0]
    start_passive_job(meterip)

def temporary_overnight_runner(count):
    # 9 minutes 45 seconds
    if not (count % 465): load_M_to_L()
    # 9 minutes 30 seconds
    if not (count % 450): load_R_to_M()
    # 10 minute
    if not (count % 480):
        print(">> 10 minutes passed. Starting another run.")
        mm.refresh()
        if len(mm.list_meters())>0:
            print(">> meter detected so go time ")
            # temporary_overnight_runner()
            threading.Thread(target=__temporary_overnight_runner, daemon=True).start()
        else:
            print(">> no meter detected so trying again in 60seconds.")
            count-=60


__belt_burner_steps = [
    load_M, load_R, load_R_to_M, load_M_to_L        # leaving out load L cause... it'll do nothing
]
def temporary_belt_burner(count):
    sec = 12
    step = (count // sec) % len(__belt_burner_steps)

    if count % sec == 0:
        func = __belt_burner_steps[step]
        func()
        

def task_refresh_meters(count):
    if count % 6 == 0:
        fresh,stale,ips = mm.refresh()
        # print(f"ips: {ips}")
        print(f"fresh: {fresh}, stale: {stale}, ips: {ips}")
        for ip in fresh: 
            print(f"fresh ip: {ip}")
            if states['mode']=='auto':
                mm.get_meter(ip).setup_custom_display()
                start_passive_job(ip)



def __interval_task():
    count = -5     # start this earlier to trigger
    count = 400
    while True:
        # reset every 24hr
        if (count := count + 1) >= 86400:
            count = 0
        try:
            # temporary_belt_burner(count)
            # temporary_overnight_runner(count)
            task_refresh_meters(count)

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
