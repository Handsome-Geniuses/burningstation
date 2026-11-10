# jobs.py
import os
import threading
import traceback
from collections import deque
from typing import Dict, Optional
from datetime import datetime
from lib.automation.tests.operator_standalone import OPERATOR_PROGRAMS
from lib.automation.shared_state import SharedState
from lib.automation.runner import run_test_job
# from lib.database import insertJobs
# from lib.meter.meter_manager import METERMANAGER as mm
from lib.database import insert_meter_jobs
from lib.hardware import hardware
from lib.meter.meter_manager import METERMANAGER as mm
from lib.sse.sse_queue_manager import SSEQM as master
from typing import Literal
from lib.meter.ssh_meter import ModuleInfo, SSHMeter
from lib.robot.robot_client import RobotClient
import json
import time
import logging
from contextlib import nullcontext
from uuid import uuid4
from lib.meter.lifecycle import session_for

from lib.system.states import states
from lib.automation.settings import *


StatusType = Literal['idle', 'running', 'finished', 'error', 'cancelled']
ResultType = Literal['pass', 'fail', None]

PROG2DEVICE = {
    "cycle_print":"printer", "printer":"printer",
    "cycle_coin_shutter":"coin shutter", "coin shutter":"coin shutter",
    "cycle_nfc":"nfc", "nfc":"nfc",
    "cycle_modem":"modem", "modem":"modem",
    "cycle_call_in":"call in", "call in":"call in", "call_in":"call in",
    "cycle_meter_ui":"screen test", "screen test":"screen test",
    "cycle_all": None,
    "operator_cycle_all": None,
    "test_operator_coins": "coins",
    "operator_coins": "coins",
    "keypad": "keypad",
    "test_operator_keypad": "keypad",
    "operator_keypad": "keypad",
    "test_operator_nfc_tap": "contactless",
    "operator_nfc_tap": "contactless",
    "test_operator_touchscreen": "touchscreen",
    "operator_touchscreen": "touchscreen",
    "test_operator_display_brightness": "display_brightness",
    "operator_display_brightness": "display_brightness",
    "test_operator_card_reader": "card_reader",
    "operator_card_reader": "card_reader",
    "test_solar": "solar",
    "test_robot_coin_shutter": "coin_shutter",
    "test_robot_keypad": "robot_keypad",
    "test_robot_display_brightness": "display_brightness",
    "robot_display_brightness": "display_brightness",
    "passive:": None,
}

PROG2MODULE = {
    "cycle_print":"printer", 
    "printer":"PRINTER",
    "cycle_coin_shutter":"COIN_SHUTTER", 
    "coin shutter":"COIN_SHUTTER",
    "coin_shutter":"COIN_SHUTTER",
    "cycle_nfc": ("KIOSK_NFC", "KIOSK_NEO"),
    "nfc": ("KIOSK_NFC", "KIOSK_NEO"),
    "nfc_gui": ("KIOSK_NFC", "KIOSK_NEO"),
    "cycle_modem":"MK7_XE910",
    "modem":"MK7_XE910",
    "cycle_call_in":"MK7_XE910",
    "call in":"MK7_XE910",
    "call_in":"MK7_XE910",
    "robot_keypad": "KEY_PAD_2",
    "robot_keypad2": "KBD_CONTROLLER",
    "keypad": "KEY_PAD_2",
    "keypad2": "KBD_CONTROLLER",
    "contactless": ("KIOSK_NFC", "KIOSK_NEO"),
    "card_reader": "EMV_CONTACT",
    "coins": "MK7_VALIDATOR",
}

def _module_info_for_program(meter: SSHMeter, program_name: str, default_info):
    modules = PROG2MODULE.get(program_name)
    if not modules:
        return default_info
    if isinstance(modules, str):
        modules = (modules,)
    for module in modules:
        info = _module_map(meter).get(module)
        if info is not None:
            return info
    return default_info


def _module_map(meter):
    session = session_for(meter)
    return session.info.get("module_info", {}) if session is not None else meter.module_info

def _wait_for_middle_bay_full(
    timeout_s: float = 20.0,
    middle_bay_channel: int = 1,
    poll_interval_s: float = 0.5,
):
    deadline = time.time() + max(timeout_s, 0.0)
    last_sensor_value = 0
    start_index = middle_bay_channel * 3
    end_index = start_index + 3

    while True:
        bay_states = states.get("mds", [False] * 9)[start_index:end_index]
        last_sensor_value = sum(int(state) << i for i, state in enumerate(bay_states))
        # print(f"Middle bay sensor value: {last_sensor_value:03b}, states: {bay_states}, time left: {deadline - time.time():.1f}s")

        if len(bay_states) == 3 and all(bay_states):
            return True, last_sensor_value
        if time.time() >= deadline:
            return False, last_sensor_value

        time.sleep(poll_interval_s)

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
        self.current_program: Optional[str] = None

    def reset(self):
        self.status = "idle"
        self.result = None
        self.last_error = None
        self.logs.clear()
        self.current_program = None

        # per-run events/state
        self.stop_event.clear()
        self.abort_event.clear()
        self.end_listener.clear()
        self.disruption_event.clear()
        self.lifecycle_observer = False
        self.attempt_epoch = None

        # per-device state
        self.current_device = None
        self.device_results.clear()
        self.device_meta.clear()
        self.extras.clear()

# Registry of jobs and threads
_states: Dict[str, JobState] = {}
_threads: Dict[str, threading.Thread] = {}
_registry_lock = threading.Lock()
def _state(ip):
    with _registry_lock:
        if ip not in _states:
            _states[ip] = JobState(ip)
        return _states[ip]


def get_frontend_job_state(meter_ip: str):
    with _registry_lock:
        st = _states.get(meter_ip)
    if st is None or st.status != "running":
        return {}

    state = {}
    if st.current_program:
        state["current_action"] = st.current_program

    keypad_state = st.extras.get("operator_keypad_state")
    if isinstance(keypad_state, dict):
        state["operator_keypad"] = dict(keypad_state)
        current = keypad_state.get("current")
        total = keypad_state.get("total")
        if isinstance(current, int) and isinstance(total, int):
            state["progress"] = {
                "current": current,
                "total": total,
            }

    feedback_state = st.extras.get("operator_feedback_state")
    if isinstance(feedback_state, dict):
        state["operator_feedback"] = dict(feedback_state)

    return state


def submit_operator_response(meter_ip: str, test: str, value: bool) -> bool:
    """Deliver an answer from an active meter dialog to its running job."""
    with _registry_lock:
        st = _states.get(meter_ip)
        if st is None or st.status != "running":
            return False
        from lib.automation.operator_feedback import submit_operator_feedback_response
        submit_operator_feedback_response(st, test, value)
        return True


def fail_operator_subtest(meter_ip: str, test: str) -> bool:
    """Fail only the active subtest of this meter's full operator run."""
    with _registry_lock:
        st = _states.get(meter_ip)
    if st is None:
        return False
    with st.lock:
        if (st.status != "running" or st.current_program != "operator_cycle_all"
                or st.current_device != test or st.abort_event.is_set()
                or st.stop_event.is_set()):
            return False
        reason = f"Operator marked {test.replace('_', ' ')} failed"
        st.extras["operator_failure"] = {"device": test, "reason": reason}
        st.stop_event.set()
    st.log(reason)
    return True

def start_job(meter_ip, program_name, kwargs, log=True, verbose=False, *, prepare=None):
    """Start the original job flow while reserving this meter's controls.

    Optional prepare(meter) performs the caller's existing UI setup synchronously
    under this same reservation; a returned dictionary supplies job kwargs.
    The worker retains controls through results display and DB handling. Subtest
    retries belong to runner/cycle functions, not to this job launcher.
    See lib/docs/meter/supervisor.md for the call order and failure paths.
    """
    meter = mm.get_meter(meter_ip)
    session = session_for(meter)
    owner = uuid4().hex
    with _registry_lock:
        if session is not None:
            if not session.claim(owner):
                return False, session.reason or "meter controls are in use"
        elif meter.status != "ready":
            return False, "job already running"
        meter.status = "busy"
    st = _state(meter_ip)
    try:
        with session.bind(owner) if session else nullcontext():
            meter.connect()
            st.reset()
            st.meter_session, st.control_owner = session, owner
            if session:
                session.shared = st
                st.attempt_epoch = session.epoch
            st.current_program = program_name
            st.status = "running"
            kwargs = dict(kwargs)
            now = datetime.now()
            if session is not None and session.supervisor is not None:
                st.set_session_log(session.supervisor)
                session.supervisor._log("job_started", program=program_name, cursor=session.supervisor.cursor)
            else:
                st.set_logfile(os.path.join("./logs", now.strftime("%Y-%m-%d"),
                                           f"{now.strftime('%H-%M-%S')}_{meter.hostname}_{program_name}.log") if log else None)
            st.log(f"STARTING JOB THREAD: {program_name} on {meter.hostname}", console=True)
            if prepare is not None:
                st.log("Preparing meter display and test options")
                prepared = prepare(meter)
                if prepared is not None:
                    kwargs.update(prepared)
            kwargs.pop("broadcast_job", None)
            st.log(f"Arguments: {kwargs}")
            st.log(f"Meter Info: {json.dumps(meter.get_info(), sort_keys=True)}")
            dev = PROG2DEVICE.get(program_name)
            if dev:
                st.current_device = dev
                st.device_results[dev] = "running"
            master.broadcast("status", {"ip": meter_ip, "status": "busy", "current_action": program_name})
    except Exception as exc:
        # No worker exists to finalize a failed setup. Publish the failure on
        # this job state before releasing its lease, so status does not remain
        # "running" after connect/get_info or setup logging raises.
        st.status, st.result = "error", "fail"
        st.current_program = program_name
        st.last_error = str(exc)
        if session is not None and session.supervisor is not None:
            try:
                session.supervisor._log("job_setup_failed", program=program_name,
                                        error=str(exc), exception_type=type(exc).__name__)
            except Exception:
                logging.exception("Unable to log job setup failure")
        if session:
            session.release(owner)
        meter.status = "ready"
        raise

    def target():
        started = time.monotonic()
        finalized = False
        try:
            with session.bind(owner) if session else nullcontext():
                run_test_job(meter, program_name, kwargs, st, log=log, verbose=verbose)
                st.result = "fail" if (st.stop_event.is_set() or any(
                    value in {"fail", "interrupted"} for value in st.device_results.values())) else "pass"
                if not st.abort_event.is_set():
                    st.status = "finished"
                st.log(f"JOB FINISHED: {st.result.upper()}", console=verbose)
                dev = PROG2DEVICE.get(program_name)
                if dev and st.device_results.get(dev) in {None, "running"}:
                    st.device_results[dev] = ("interrupted" if st.extras.get("meter_disruption")
                                              else "fail" if st.stop_event.is_set() else "pass")
                meter.results.update(st.device_results)
                meter.results[program_name] = st.result
                st.extras["duration_s"] = round(time.monotonic() - started, 3)
                st.extras["kwargs"] = kwargs
                master.broadcast("devices", {"ip": meter_ip, "results": st.device_results})
                job_done(meter_ip, meter=meter, st=st)
                finalized = True
                if os.name != "nt" and (session is None or session.ready):
                    meter.beep(3)
        except Exception as exc:
            st.status, st.result = "error", "fail"
            st.last_error = str(exc)
            st.log(f"JOB FINALIZATION ERROR: {exc}", console=True)
        finally:
            try:
                st.flush_logs()
                if session is not None and session.supervisor is not None:
                    session.supervisor._log("job_finalized", program=program_name,
                                            result=st.result, cursor=session.supervisor.cursor)
            except Exception:
                logging.exception("Unable to flush final job logs")
            if session:
                session.release(owner)
            meter.status = "ready"
            # A retained object is never allowed to publish into a new session
            # which happens to reuse its IP address.
            if mm.meters.get(meter_ip) is meter:
                master.broadcast("status", {"ip": meter_ip, "status": meter.status, "current_action": ""})
                if session:
                    master.broadcast("meter", {"ip": meter_ip, "alive": True, "info": meter.public_info()})
                if (finalized and not st.abort_event.is_set() and not st.extras.get("meter_disruption")
                        and (session is None or session.ready)):
                    _handle_auto_job_done(meter_ip, program_name)

    thread = threading.Thread(target=target, daemon=True, name=f"job:{meter_ip}:{program_name}")
    _threads[meter_ip] = thread
    thread.start()
    return True, "started"




def stop_job(meter_ip):
    """Request cancellation; the worker, not this request, releases controls."""
    st = _state(meter_ip)
    meter = mm.get_meter(meter_ip)
    if (st.status!='running' and meter.status!='busy'):
        master.broadcast('status', {'ip':meter_ip, 'status': meter.status, 'msg': 'tried stopping a non busy meter', 'current_action': ''})

    st.log(f"JOB CANCELLED BY USER", console=True)
    st.flush_logs()

    st.extras["failure_reason"] = "manually stopped"
    if not st.last_error:
        st.last_error = "manually stopped"
    with st.lock:
        st.abort_event.set()
        st.stop_event.set()
        st.status = "cancelled"
    # Cancellation is a request. The worker retains its lease through cleanup.
    master.broadcast('status', {'ip':meter_ip, 'status': 'busy', 'current_action': 'stopping'})

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
    """Prepare the original passive display/options, then launch cycle_all."""
    def prepare(meter):
        meter.set_ui_mode("banner")
        modules = meter.module_info
        meter.setup_custom_display()
        return build_passive_kwargs(modules)

    return start_job(meter_ip, "cycle_all", {}, verbose=True, prepare=prepare)


def start_physical_job(meter_ip, buttons=None):
    """Keep the bay check, brightness/setup order, and post-start clearance delay."""
    loaded, sensor_value = _wait_for_middle_bay_full(timeout_s=20.0)
    if not loaded:
        msg = f"Cannot start physical job since station M is not fully occupied; middle-bay sensors read {sensor_value:03b} (expected 111)"
        master.broadcast('notify', {'ntype': 'error', 'msg': msg})
        return False, msg

    def prepare(meter):
        robot = RobotClient()
        robot.flush_event_queue()
        modules = meter.module_info
        meter.set_brightness(15)
        meter.setup_custom_display()
        selected = get_default_buttons(modules, meter.meter_type) if not buttons else buttons
        return build_physical_kwargs(modules, buttons=selected)

    success, msg = start_job(meter_ip, "physical_cycle_all", {}, verbose=True, prepare=prepare)
    time.sleep(5) # incase robot needs to get out of there
    return success, msg


def start_operator_job(meter_ip):
    """Build operator options under the same meter reservation as display setup."""
    def prepare(meter):
        modules = meter.module_info
        buttons = get_default_buttons(modules, meter.meter_type)
        meter.set_ui_mode("banner")
        meter.setup_custom_display()
        return build_operator_kwargs(
            modules, buttons=buttons, meter_region=getattr(meter, "meter_region", None),
        )

    return start_job(meter_ip, "operator_cycle_all", {}, verbose=True, prepare=prepare)


def start_operator_test_job(meter_ip, test):
    """Run one selected operator test while preserving its configured options."""
    if test not in OPERATOR_PROGRAMS:
        return False, "unknown operator test"
    meter = mm.get_meter(meter_ip)
    if meter.status != "ready":
        return False, "job already running"
    modules = meter.module_info
    buttons = get_default_buttons(modules, meter.meter_type)
    device = OPERATOR_PROGRAMS[test]
    config = build_operator_kwargs(
        modules, buttons=buttons, meter_region=getattr(meter, "meter_region", None),
    )[device]
    if device == "keypad" and not buttons:
        return False, "operator keypad has no buttons to test"

    def prepare(meter):
        meter.set_ui_mode("banner")
        meter.setup_custom_display()

    # Individual OP buttons always run once, retaining the test's other options.
    return start_job(meter_ip, test, {**config, "job_count": 1}, verbose=True, prepare=prepare)


def start_operator_keypad_job(meter_ip):
    return start_operator_test_job(meter_ip, "operator_keypad")


def _handle_auto_job_done(meter_ip, current_program):
    auto_actions = {
        "cycle_all": "passive",
        "physical_cycle_all": "physical",
    }
    auto_action = auto_actions.get(current_program)
    if auto_action is None:
        return

    if states.get("mode") != "auto":
        master.broadcast(
            "notify",
            {
                "ntype": "info",
                "msg": f"Auto skipped after {auto_action}; mode is {states.get('mode')}",
            },
        )
        return

    if not hardware.has("auto_mode"):
        master.broadcast(
            "notify",
            {
                "ntype": "info",
                "msg": f"Auto skipped after {auto_action}; hardware profile does not support auto mode",
            },
        )
        return

    from lib.system.auto import AUTO_COORDINATOR

    if current_program == "cycle_all":
        AUTO_COORDINATOR.on_passive_done(meter_ip)
    elif current_program == "physical_cycle_all":
        AUTO_COORDINATOR.on_physical_done(meter_ip)


def _job_has_failure(st: JobState) -> bool:
    return (
        st.result == "fail"
        or st.stop_event.is_set()
        or any(status in {"fail", "interrupted"} for status in st.device_results.values())
    )


def _job_failure_reason(st: JobState, device: str | None = None) -> str:
    explicit_reason = st.extras.get("failure_reason")
    if explicit_reason:
        return _format_job_failure_reason(st, str(explicit_reason), device)
    if st.last_error:
        return _format_job_failure_reason(st, str(st.last_error), device)

    if device:
        meta = st.device_meta.get(device)
        if isinstance(meta, dict) and meta.get("error"):
            return _format_job_failure_reason(st, str(meta["error"]), device)

    for meta in st.device_meta.values():
        if isinstance(meta, dict) and meta.get("error"):
            return _format_job_failure_reason(st, str(meta["error"]), device)

    return "failed"


def _format_job_failure_reason(
    st: JobState,
    reason: str,
    device: str | None = None,
) -> str:
    if reason != "manually stopped":
        return reason

    missing = None
    if device:
        meta = st.device_meta.get(device)
        if isinstance(meta, dict):
            missing = meta.get("missing")

    if not missing:
        for meta in st.device_meta.values():
            if isinstance(meta, dict) and meta.get("missing"):
                missing = meta["missing"]
                break

    if isinstance(missing, dict) and missing:
        return f"{reason}; missing={missing}"
    return reason


def _normalize_device_status(status, fallback_status: str) -> str:
    if status in (None, "running"):
        return fallback_status
    return status


def _build_keypad_job_results(meter: SSHMeter, keypad_status: str, error: str | None = None):
    default_info = {'ver': -1, 'mod': -1, 'id': -1}
    info = _module_info_for_program(meter, "keypad", default_info)
    job_results = {
        "keypad": {
            "status": keypad_status,
            "fw": info.get("ver", -1),
            "id": info.get("id", -1),
        }
    }
    if error:
        job_results["keypad"]["error"] = error

    keypad2_info = _module_map(meter).get(PROG2MODULE.get("keypad2"))
    if keypad2_info is not None:
        job_results["keypad2"] = {
            "status": keypad_status,
            "fw": keypad2_info.get("ver", -1),
            "id": keypad2_info.get("id", -1),
        }

    return job_results


# using this to database?
def job_done(meter_ip, *, meter=None, st=None):
    meter = meter if meter is not None else mm.get_meter(meter_ip)
    st = st if st is not None else _state(meter_ip)
    current_program = st.current_program

    meter.results.pop(current_program, None)

    # initial 
    overall_status = "pass"
    data = {"kwargs": st.extras.get('kwargs', {}),
            "meter_session": st.extras.get("meter_session"),
            "meter_interruptions": st.extras.get("meter_interruptions", []),
            "meter_disruption": st.extras.get("meter_disruption")}
    
    # for cycle all passive
    if current_program == 'cycle_all':
        for key, val in st.device_results.items():
            if val in {"fail", "interrupted"}:
                overall_status = "fail"
                break

        default_info = {'ver': -1, 'mod': -1, 'id': -1}
        job_results = {}
        for key, val in st.device_results.items():
            info = _module_info_for_program(meter, key, default_info)

            job_results[key] = {
                "status": val,
                "fw": info.get('ver', -1),
                "id": info.get('id', -1)
            }

        data["results"]=job_results
        if st.last_error: data["last_error"] = st.last_error
        if st.device_meta: data["device_meta"] = st.device_meta

    elif current_program == "physical_cycle_all":
        for key, val in st.device_results.items():
            if val in {"fail", "interrupted"}:
                overall_status = "fail"
                break

        default_info = {'ver': -1, 'mod': -1, 'id': -1}
        job_results = {}
        for key, val in st.device_results.items():
            info = _module_info_for_program(meter, key, default_info)

            job_results[key] = {
                "status": val,
                "fw": info.get("ver", -1),
                "id": info.get("id", -1),
            }
            if key == "robot_keypad":
                info = _module_map(meter).get(PROG2MODULE.get("robot_keypad2"), default_info)
                job_results["robot_keypad2"] = {
                    "status": val,
                    "fw": info.get("ver", -1),
                    "id": info.get("id", -1),
                }

        data["results"] = job_results
        if st.last_error:
            data["last_error"] = st.last_error
        if st.device_meta:
            data["device_meta"] = st.device_meta

    elif current_program == "operator_cycle_all":
        for key, val in st.device_results.items():
            if val in {"fail", "interrupted"}:
                overall_status = "fail"
                break

        default_info = {'ver': -1, 'mod': -1, 'id': -1}
        job_results = {}
        for key, val in st.device_results.items():
            info = _module_info_for_program(meter, key, default_info)

            job_results[key] = {
                "status": val,
                "fw": info.get("ver", -1),
                "id": info.get("id", -1),
            }
            if key == "keypad":
                info = _module_map(meter).get(PROG2MODULE.get("keypad2"), default_info)
                job_results["keypad2"] = {
                    "status": val,
                    "fw": info.get("ver", -1),
                    "id": info.get("id", -1),
                }

        data["results"] = job_results
        if st.last_error:
            data["last_error"] = st.last_error
        if st.device_meta:
            data["device_meta"] = st.device_meta

    # insertion time!
    elif current_program in OPERATOR_PROGRAMS:
        device = OPERATOR_PROGRAMS[current_program]
        failed = _job_has_failure(st)
        overall_status = "fail" if failed else "pass"
        failure_reason = _job_failure_reason(st, device) if failed else None
        device_status = _normalize_device_status(
            st.device_results.get(device),
            overall_status,
        )

        if device == "keypad":
            data["results"] = _build_keypad_job_results(meter, device_status, failure_reason)
        else:
            info = _module_info_for_program(meter, device, {"ver": -1, "id": -1})
            data["results"] = {device: {
                "status": device_status, "fw": info.get("ver", -1), "id": info.get("id", -1),
            }}
            if failure_reason:
                data["results"][device]["error"] = failure_reason
        data["duration_s"] = st.extras.get("duration_s", 0)
        if st.last_error:
            data["last_error"] = st.last_error
        if failure_reason:
            data["failure_reason"] = failure_reason
        if st.device_meta:
            data["device_meta"] = st.device_meta

    # Publish before database I/O so station activity survives database outages.
    if _job_has_failure(st):
        overall_status = "fail"
    data["duration_s"] = st.extras.get("duration_s")
    if overall_status == "fail":
        data["failure_reason"] = _job_failure_reason(st)
    master.publish_activity(
        "job", hostname=meter.hostname, name=current_program,
        status=overall_status, data=data,
    )

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

    # Operator-visible results come first: a DB outage must not hide them.
    # Keep this order; production DB insertion has raised after successful tests.
    if current_program in {"cycle_all", "physical_cycle_all", "operator_cycle_all"}:
        meter.update_display_results(st)
    if meter.db_id is not None:
        insert_meter_jobs(meter.db_id,[job_data],'\n'.join(line.rstrip('\n') for line in st.logs))
    # if st.logs successfully inserted to db, rm log file maybe?

    if current_program == "cycle_all" and store.settings.other.auto_print_fw:
        meter.custom_print()
        time.sleep(5)

if __name__ == "__main__":
    # import tools.mock
    import time
    fresh,stale,meters = mm.refresh()
    # for f in fresh: print(f)
    # ip = meters[0]
    ip = "192.168.169.34"
    # print(ip)
    meter = mm.get_meter(ip)

    # start_passive_job(ip) 
    start_job(ip, "test_solar", {"count":1})
    # input("press enter to stop\n")
    while meter.status != "ready": time.sleep(1)
    

