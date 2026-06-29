# ====================================================
# 
# ====================================================
import threading
import time
from lib.automation.jobs import _state, start_job, start_passive_job, start_physical_job, stop_job
from lib.gpio import HWGPIO, HWGPIO_MONITOR, emergency
from asyncdec import AsyncManager, async_fire_and_forget
from lib.meter.meter_manager import METERMANAGER as mm
from lib.sse.sse_queue_manager import SSEQM as master
from lib.system import states

am_program = AsyncManager("am_program")
def emergency_event(p:HWGPIO):
    if p.state: am_program.emergency_stop()
    else: am_program.emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,emergency_event)


@am_program.operation(timeout=10)
def some_program():
    pass


def dummyjob(meter_ip):
    st = _state(meter_ip)
    if st.current_program == "dummy" and st.status == "running":
        states['dummy'].setdefault(meter_ip, {})['dummy'] = False
    else:
        start_job(meter_ip, "dummy", {})


def stop_passive_job(meter_ip):
    return stop_job(meter_ip)

def stop_physical_job(meter_ip):
    return stop_job(meter_ip)


def meter_from_kwargs(**kwargs):
    meter_ip = kwargs.get('meter_ip', None)
    if meter_ip == None: meter_ip = next(iter(mm.meters), None)
    meter = mm.get_meter(meter_ip) if meter_ip else None
    return meter_ip, meter


# ----------------------------------------------------
# determine manual action
# ----------------------------------------------------
@am_program.operation(timeout=30)
def manual_action(**kwargs):
    if states['mode'] != 'manual':
        return "System not in manual mode", 409
    program = kwargs.get('program', None)
    meter_ip, meter = meter_from_kwargs(**kwargs)

    if not program or not meter: return
    elif program == "setup_custom_display":
        if meter: meter.setup_custom_display()
    elif program == "start_passive_job":
        if meter: start_passive_job(meter_ip)
    elif program == "stop_passive_job":
        if meter: stop_passive_job(meter_ip)
    elif program == "start_physical_job":
        if meter: start_physical_job(meter_ip)
    elif program == "stop_physical_job":
        if meter: stop_physical_job(meter_ip)


    elif program == "hello": print("hello from program.py", {})
        
    else: return "Unknown action", 400


# ----------------------------------------------------
# determine automatic action
# ----------------------------------------------------
@am_program.operation(timeout=30)
def automatic_action(**kwargs):
    if states['mode'] != 'auto':
        return "System not in auto mode", 409
    program = kwargs.get('program', None)
    meter_ip, meter = meter_from_kwargs(**kwargs)

    if not program or not meter: return
    if False: pass
    else: return "Unknown action", 400


# ----------------------------------------------------
# meter-only actions that do not care about system mode
# ----------------------------------------------------
@am_program.operation(timeout=30)
def neutral(**kwargs):
    program = kwargs.get('program', None)
    meter_ip, meter = meter_from_kwargs(**kwargs)

    if not program or not meter: return
    if False: pass
    elif program == "identify": meter.blink()
    elif program == "identify_until":
        meter.blink_until_start(
            max_duration=float(kwargs.get('max_duration', 60.0)),
            on_done=lambda: master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': ''}),
        )
        master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': 'blinking'})
    elif program == "identify_stop":
        meter.blink_until_stop()
        master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': ''})
    elif program == "printfw": meter.custom_print()
    elif program == "dummy": dummyjob(meter_ip)






    elif program == "start_passive_job":
        if meter: start_passive_job(meter_ip)
    elif program == "stop_passive_job":
        if meter: stop_passive_job(meter_ip)
    elif program == "start_physical_job":
        if meter: start_physical_job(meter_ip)
    elif program == "stop_physical_job":
        if meter: stop_physical_job(meter_ip)






    else: return "Unknown action", 400

def on_action(action, **kwargs):
    res = None
    if False: pass
    elif action=="some_program": res = some_program(**kwargs)
    elif action=="manual": res = manual_action(**kwargs)
    elif action=="automatic": res = automatic_action(**kwargs)
    elif action=="neutral": res = neutral(**kwargs)
    return res if res is not None else ("", 200)

__all__ = ['on_action']
