# ====================================================
# 
# ====================================================
import threading
import time
from lib.automation.jobs import start_passive_job, start_physical_job
from lib.gpio import HWGPIO, HWGPIO_MONITOR, emergency
from asyncdec import AsyncManager, async_fire_and_forget
from lib.meter.meter_manager import METERMANAGER as mm
from lib.system import states

am_program = AsyncManager("am_program")
def emergency_event(p:HWGPIO):
    if p.state: am_program.emergency_stop()
    else: am_program.emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,emergency_event)


@am_program.operation(timeout=10)
def some_program():
    pass

# ----------------------------------------------------
# determine manual action
# ----------------------------------------------------
@am_program.operation(timeout=30)
def manual_action(**kwargs):
    if states['mode'] != 'manual':
        return "System not in manual mode", 409
    program = kwargs.get('program', None)
    meter_ip = kwargs.get('meter_ip', None)
    if meter_ip == None: meter_ip = next(iter(mm.meters), None)
    meter = mm.get_meter(meter_ip) if meter_ip else None

    if not program or not meter: return
    elif program == "setup_custom_display":
        if meter: meter.setup_custom_display()
    elif program == "start_passive_job":
        if meter: start_passive_job(meter_ip)
    elif program == "start_physical_job":
        if meter: start_physical_job(meter_ip)
    elif program == "hello":
        print("hello from program.py")
    else: return "Unknown action", 400

def on_action(action, **kwargs):
    res = None
    if False: pass
    elif action=="some_program": res = some_program(**kwargs)
    elif action=="manual": res = manual_action(**kwargs)
    return res if res is not None else ("", 200)

__all__ = ['on_action']

