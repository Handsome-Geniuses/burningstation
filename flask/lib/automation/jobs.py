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
from lib.meter.meter_manager import METERMANAGER as mm
from lib.sse.sse_queue_manager import SSEQM as master
from typing import Literal
from lib.meter.ssh_meter import ModuleInfo
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

        print(f"[DEBUG][AFTER TEST] program={program_name} result={st.result}")
        if dev_results:
            print("[DEBUG][AFTER TEST] per-device:", {d:r for d,r in dev_results.items()})
        else:
            print("[DEBUG][AFTER TEST] per-device: none")

        meter.results.update(dev_results)
        print(f'meter.results: {meter.results}')
        master.broadcast('devices', {'ip': meter_ip, 'results': dev_results})

        meter.status = "ready"
        result = 'success' if st.result == 'pass' else 'error' if st.result == 'fail' else 'info'
        meter.results[program_name] = st.result
        master.broadcast('status', {'ip':meter_ip, 'status': meter.status, 'msg': ''})
        if (broadcast_job): 
            master.broadcast('job', {'ip':meter_ip, 'name': program_name, 'result': result, 'msg': st.device_meta})
            journalctl = '\n'.join(line.rstrip('\n') for line in st.logs)
            jobNotes = { 'kwargs': kwargs }
            if program_name=='all tests': jobNotes['results'] = st.device_results
            jobNotes = json.dumps(jobNotes)

            # removed this cause listener can stop too so wouldn't work. i'll deal with it later.
            # userNotes = 'user stopped' if (st.stop_event.is_set()) else ''

            payload = {
                'name': program_name,
                'status': st.result,
                'jobNotes': jobNotes,   # string! use json.stringify if needed
                # 'userNotes': userNotes, # string! use json.stringify if needed
                'journalctl': journalctl
            }

            fwkey = PROG2MODULE.get(program_name)
            if fwkey:
                module:ModuleInfo = meter.module_info.get(fwkey)
                if module:
                    payload['moduleFw'] = int(module.get('fw',-1))
                    payload['moduleId'] = int(module.get('full_id', -1))
                    
            # insertJobs(meter.hostname,[payload])

        meter.beep(3)

        if program_name in ['cycle_all', 'all tests'] and meter.meter_type != 'msx':
            meter.custom_print()

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



if __name__ == "__main__":
    # print(job_status("192.168.137.157"))
    mm.refresh()


    start_job("192.168.137.157","cycle_print",{"count":1})
    import time
    while True:
        time.sleep(1)
        print(job_status("192.168.137.157"))
        