# jobs.py
import os
import threading
import traceback
from collections import deque
from typing import Dict, Optional
from datetime import datetime
from lib.automation.tests import get_monitors
from lib.automation.shared_state import SharedState
from lib.automation.runner import run_test_job
# from lib.database import insertJobs
# from lib.meter.meter_manager import METERMANAGER as mm
from lib.database import insert_meter_jobs
from lib.meter.meter_manager import METERMANAGER as mm
from lib.sse.sse_queue_manager import SSEQM as master
from typing import Literal
from lib.meter.ssh_meter import ModuleInfo, SSHMeter
from lib.robot.robot_client import RobotClient
import json
import requests
import time

from lib.system.states import states


StatusType = Literal['idle', 'running', 'finished', 'error', 'cancelled']
ResultType = Literal['pass', 'fail', None]

PROG2DEVICE = {
    "cycle_print":"printer", "printer":"printer",
    "cycle_coin_shutter":"coin shutter", "coin shutter":"coin shutter",
    "cycle_nfc":"nfc", "nfc":"nfc",
    "cycle_modem":"modem", "modem":"modem",
    "cycle_meter_ui":"screen test", "screen test":"screen test",
    "cycle_all": None,
    "keypad": "keypad",
    "passive:": None,
}

PROG2MODULE = {
    "cycle_print":"printer", 
    "printer":"PRINTER",
    "cycle_coin_shutter":"COIN_SHUTTER", 
    "coin shutter":"COIN_SHUTTER",
    "cycle_nfc":"KIOSK_NFC", 
    "nfc":"KIOSK_NFC",
    "cycle_modem":"MK7_XE910", 
    "modem":"MK7_XE910",
}

def get_default_buttons(modules, meter_type):
    buttons = []
    if "KEY_PAD_2" in modules:
        buttons += ['1', '2', '3', '4', '5', 'ASTERISK', '6', '7', '8', '9', '0', 'POUND', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'BACK', 'Y', 'Z', 'ENTER']

    if "KBD_CONTROLLER" in modules and meter_type == "ms2.5":
        buttons += ['help', 'up', 'down', 'cancel', 'accept', 'max']
    elif "KBD_CONTROLLER" in modules and meter_type == "ms3":
        buttons += ['help', 'up', 'down', 'cancel', 'accept', 'max'] # skip "center" bc it resets the meter program/display
    
    return buttons

class JobState(SharedState):
    def __init__(self, meter_ip):
        super().__init__()
        self.meter_ip:str                   = meter_ip
        self.status:StatusType              = "idle"        # idle|running|finished|error|cancelled
        self.result:ResultType              = None          # pass|fail|None
        self.last_error: Optional[str]      = None
        self.current_program: Optional[str] = None

    def reset(self):
        self.status = "idle"
        self.result = None
        self.last_error = None
        self.logs.clear()
        self.current_program = None

        # per-run events/state
        self.stop_event.clear()
        self.end_listener.clear()
        self.success_event.clear()

        # per-device state
        self.current_device = None
        self.device_results.clear()
        self.device_meta.clear()

# Registry of jobs and threads
_states: Dict[str, JobState] = {}
_threads: Dict[str, threading.Thread] = {}
_registry_lock = threading.Lock()

def _state(ip):
    with _registry_lock:
        if ip not in _states:
            _states[ip] = JobState(ip)
        return _states[ip]

def start_job(meter_ip, program_name, kwargs, log=True, verbose=False):
    meter = mm.get_meter(meter_ip)
    st = _state(meter_ip)

    if meter.status != 'ready': return False, "job already running"

    st.reset()
    if log:
        log_dir = "./logs"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        logfile_name = f"[{meter.hostname}]{ts}-{program_name}.log"
        logfile_path = os.path.join(log_dir, logfile_name)
        st.set_logfile(logfile_path)
    else:
        st.set_logfile(None)

    st.log(f"STARTING JOB THREAD: {program_name} on {meter.hostname}", console=True)
    st.log(f"Arguments: {kwargs}")

    meter.status = "busy"
    master.broadcast('status', {'ip':meter_ip, 'status': meter.status})
    st.status = "running"
    st.current_program = program_name

    dev = PROG2DEVICE.get(program_name)
    if dev:
        st.current_device = dev
        st.device_results[dev] = "running"
        st.set_allowed({dev}, reason=f"Start job {program_name}")
    else:
        st.set_allowed(set(), reason=f"Start job {program_name} (no monitors expected)")
    

    broadcast_job = kwargs.pop('broadcast_job', True)

    def target():
        try:
            run_test_job(
                meter=meter,
                program_name=program_name,
                automation_kwargs=kwargs,
                shared=st,
                log=log,
                verbose=verbose,
            )
            st.result  = "pass" if not st.stop_event.is_set() else "fail"
            st.status  = "finished"
            st.last_error = ''
            st.log(f"JOB FINISHED: {st.result.upper()}", console=verbose)

            meter.results[program_name] = st.result
        
        except Exception as exc:
            st.log(f"JOB CRASHED: {exc}", console=True)
            
            st.status = "error"
            st.result = "fail"
            st.last_error = "".join(traceback.format_exception_only(type(exc), exc)).strip()

            meter.results[program_name] = st.result
        finally:
            st.flush_logs()

        dev_results = getattr(st, "device_results", {}) or {}
        dev = PROG2DEVICE.get(program_name)
        if dev:
            status = dev_results.get(dev)
            if status is None or status == "running":
                dev_results[dev] = 'fail' if st.stop_event.is_set() else 'pass'

        meter.results.update(dev_results)
        st.log(f"meter.results: {meter.results}", console=True)
        master.broadcast('devices', {'ip': meter_ip, 'results': dev_results})

        meter.status = "ready"
        meter.results[program_name] = st.result
        master.broadcast('status', {'ip':meter_ip, 'status': meter.status, 'msg': ''})

        st.extras['kwargs'] = kwargs
        job_done(meter_ip)
        meter.beep(3)

        # if program_name in ['cycle_all', 'all tests'] and meter.meter_type != 'msx':
            # meter.custom_print()

    t = threading.Thread(target=target, daemon=True)
    _threads[meter_ip] = t
    t.start()
    if (meter): meter.status = "busy"
    return True, "started"



def stop_job(meter_ip):
    st = _state(meter_ip)
    meter = mm.get_meter(meter_ip)
    if (st.status!='running' and meter.status!='busy'): 
        master.broadcast('status', {'ip':meter_ip, 'status': meter.status, 'msg': 'tried stopping a non busy meter'})

    st.log(f"JOB CANCELLED BY USER", console=True)
    st.flush_logs()
    
    st.stop_event.set()
    st.status = "cancelled"
    meter.status = "ready"
    meter.beep(3)

    return True

def job_status(meter_ip):
    st = _state(meter_ip)
    with st.lock:
        return {
            "meter_ip"   : meter_ip,
            "status"     : st.status,
            "result"    : st.result,
            "last_error" : st.last_error,
            "current_program": st.current_program,
        }


def start_passive_job(meter_ip):
    meter = mm.get_meter(meter_ip)
    modules = meter.module_info
    has_nfc = "KIOSK_NFC" in modules
    has_modem = "MK7_XE910" in modules
    has_printer = "PRINTER" in modules
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_screen_test = True  # all meters have screen test

    kwargs = {
        "nfc": 1 if has_nfc else 0,
        "modem": 1 if has_modem else 0 ,
        "printer": 1 if has_printer else 0,
        "coin shutter": 1 if has_coin_shutter else 0,
        "screen test": 1 if has_screen_test else 0,
        "numBurnCycles": 1,
        "numBurnDelay": 10   
    }

    response = requests.post("http://127.0.0.1:8011/api/system/station/load", json={"type":"L"})
    start_job(meter_ip, "cycle_all", kwargs, verbose=True)


def start_physical_job(meter_ip, buttons=None):
    robot = RobotClient()
    robot.flush_event_queue()

    time.sleep(10) # wait for meter to move from L to M
    meter = mm.get_meter(meter_ip)
    modules = meter.module_info
    meter.set_brightness(15)
    meter.setup_custom_display()
    
    has_solar = True
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_nfc = "KIOSK_NFC" in modules
    buttons = get_default_buttons(modules, meter.meter_type) if not buttons else buttons

    kwargs = {
        "numBurnCycles": 1,
        "numBurnDelay": 5,
        "solar": {"enabled": has_solar},
        "coin_shutter": {"enabled": has_coin_shutter},
        "nfc": {"enabled": has_nfc},
        "robot_keypad": {"enabled": bool(buttons), "buttons": buttons},

        "monitors": [
            ("nfc", {"timeout_on_s": 6.0, "timeout_off_s": 5.0}),
            ("robot_keypad", {"buttons": buttons})
        ]
    }

    success, msg = start_job(meter_ip, "physical_cycle_all", kwargs, verbose=True)
    time.sleep(5) # incase robot needs to get out of there



# using this to database?
def job_done(meter_ip):
    meter = mm.get_meter(meter_ip)
    st = _state(meter_ip)
    status = job_status(meter_ip)
    current_program = status.get("current_program")
    if meter.db_id==None: return
    meter.results.pop(current_program)

    # initial 
    overall_status = "pass"
    data = {"kwargs": st.extras.get('kwargs', {})}
        
    # for cycle all passive
    if current_program == 'cycle_all':
        response = requests.post("http://127.0.0.1:8011/api/system/station/load", json={"type":"M"})

        for key, val in meter.results.items():
            if val == "fail":
                overall_status = "fail"
                break

        default_info = {'ver': -1, 'mod': -1, 'id': -1}
        job_results = {}
        for key, val in meter.results.items():
            info = meter.module_info.get(PROG2MODULE.get(key), default_info)

            job_results[key] = {
                "status": val,
                "fw": info.get('ver', -1),
                "id": info.get('id', -1)
            }

        data["results"]=job_results
        if st.last_error: data["last_error"] = st.last_error
        if st.device_meta: data["device_meta"] = st.device_meta

        if states['mode'] == 'auto':
            start_physical_job(meter.host)

    elif current_program == "physical_cycle_all" and states["mode"] == "auto":
        response = requests.post("http://127.0.0.1:8011/api/system/station/load", json={"type":"R"})
    
    # insertion time!
    job_data = {
        "name": current_program,
        "status": overall_status,
        "data": data
    }

    st.log("=== JOB SUMMARY ===")
    st.log(f"Overall Result: {overall_status.upper()}")
    st.log(f"Program: {current_program}")
    st.log(f"Device Results: {st.device_results}")
    st.log(f"Device Metadata: {st.device_meta}")
    st.log(f"Extras: {st.extras}")
    st.log(f"Last Error: {st.last_error}")
    st.log("=== END OF JOB ===")
    st.flush_logs()

    meter.update_display_results(st)
    insert_meter_jobs(meter.db_id,[job_data],'\n'.join(line.rstrip('\n') for line in st.logs))
    # if st.logs successfully inserted to db, rm log file maybe?


if __name__ == "__main__":
    # import tools.mock
    import time
    fresh,stale,meters = mm.refresh()
    # for f in fresh: print(f)
    # ip = meters[0]
    ip = "192.168.137.32"
    # print(ip)
    meter = mm.get_meter(ip)

    start_passive_job(ip) 
    # start_job(ip, "screen test", {"count":1})
    # input("press enter to stop\n")
    while meter.status != "ready": time.sleep(1)
    

