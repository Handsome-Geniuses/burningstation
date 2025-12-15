# jobs.py
import threading
import traceback
from collections import deque
from typing import Dict, Optional
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
import json


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
        buttons += ['help', 'up', 'down', 'center', 'cancel', 'accept', 'max']
    
    return buttons

class JobState(SharedState):
    def __init__(self, meter_ip):
        super().__init__()
        self.meter_ip:str                   = meter_ip
        self.status:StatusType              = "idle"        # idle|running|finished|error|cancelled
        self.result:ResultType              = None          # pass|fail|None
        self.last_error: Optional[str]      = None
        # self.logs                           = deque(maxlen=400)
        self.logs                           = []
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

            meter.results[program_name] = st.result

        except Exception as exc:
            st.status, st.result = "error", "fail"
            # st.result = "fail"
            meter.results[program_name] = st.result

            st.last_error = "".join(traceback.format_exception_only(type(exc), exc)).strip()

        dev_results = getattr(st, "device_results", {}) or {}
        dev = PROG2DEVICE.get(program_name)
        if dev:
            status = dev_results.get(dev)
            if status is None or status == "running":
                dev_results[dev] = 'fail' if st.stop_event.is_set() else 'pass'

        if verbose:
            print(f"[DEBUG] program={program_name} result={st.result}")
            if dev_results:
                print("[DEBUG] per-device:", {d:r for d,r in dev_results.items()})
            else:
                print("[DEBUG] per-device: none")

        meter.results.update(dev_results)
        print(f'meter.results: {meter.results}')
        master.broadcast('devices', {'ip': meter_ip, 'results': dev_results})

        meter.status = "ready"
        result = 'success' if st.result == 'pass' else 'error' if st.result == 'fail' else 'info'
        meter.results[program_name] = st.result
        master.broadcast('status', {'ip':meter_ip, 'status': meter.status, 'msg': ''})


        # this was the old meter jobs database insert logic gonna remove
        # if (broadcast_job): 
        #     master.broadcast('job', {'ip':meter_ip, 'name': program_name, 'result': result, 'msg': st.device_meta})
        #     journalctl = '\n'.join(line.rstrip('\n') for line in st.logs)
        #     jobNotes = { 'kwargs': kwargs }
        #     if program_name=='all tests': jobNotes['results'] = st.device_results
        #     jobNotes = json.dumps(jobNotes)

        #     # removed this cause listener can stop too so wouldn't work. i'll deal with it later.
        #     # userNotes = 'user stopped' if (st.stop_event.is_set()) else ''

        #     payload = {
        #         'name': program_name,
        #         'status': st.result,
        #         'jobNotes': jobNotes,   # string! use json.stringify if needed
        #         # 'userNotes': userNotes, # string! use json.stringify if needed
        #         'journalctl': journalctl
        #     }

        #     fwkey = PROG2MODULE.get(program_name)
        #     if fwkey:
        #         module:ModuleInfo = meter.module_info.get(fwkey)
        #         if module:
        #             payload['moduleFw'] = int(module.get('fw',-1))
        #             payload['moduleId'] = int(module.get('full_id', -1))
                    
        #     # insertJobs(meter.hostname,[payload])
        #     # print(payload)
        #     print(journalctl)

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

    start_job(meter_ip, "cycle_all", kwargs)


def start_physical_job(meter_ip, buttons=None):
    meter = mm.get_meter(meter_ip)
    modules = meter.module_info
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_nfc = "KIOSK_NFC" in modules
    buttons = get_default_buttons(modules, meter.meter_type) if not buttons else buttons

    kwargs = {
        "numBurnCycles": 1,
        "numBurnDelay": 5,
        "coin_shutter": {"enabled": has_coin_shutter},
        "nfc": {"enabled": has_nfc},
        "robot_keypad": {"enabled": bool(buttons), "buttons": buttons},

        "monitors": [
            ("nfc", {"timeout_on_s": 6.0, "timeout_off_s": 3.0}),
            ("robot_keypad", {"buttons": buttons})
        ]
    }

    success, msg = start_job(meter_ip, "physical_cycle_all", kwargs, verbose=True)
    # print(f"[START_PHYSICAL_JOB] start_job() returned: {success} | {msg}")


# using this to database?
def job_done(meter_ip):
    meter = mm.get_meter(meter_ip)
    st = _state(meter_ip)
    status = job_status(meter_ip)
    current_program = status.get("current_program")
    if current_program=='cycle_all':
        if meter.db_id==None: return
        meter.results.pop("cycle_all")

        overall = "pass"
        for key, val in meter.results.items():
            if val == "fail":
                overall = "fail"
                break
        jobs = [{
            "name": current_program,
            "status": overall,
            "data": {
                "results": meter.results,
                "journalctl": '\n'.join(line.rstrip('\n') for line in st.logs)
            }
        }]
        
        insert_meter_jobs(meter.db_id,jobs)

if __name__ == "__main__":
    import tools.mock
    import time
    fresh,stale,meters = mm.refresh()
    for f in fresh: print(f)
    # ip = meters[0]
    # print(ip)
    # meter = mm.get_meter(ip)
    # start_passive_job(ip) 
    # # start_job(ip, "screen test", {"count":1})


    # # input("press enter to stop\n")
    # while meter.status != "ready": time.sleep(1)
    

