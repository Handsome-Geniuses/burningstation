from unittest.mock import patch
import ip_scanner
import time

from lib.automation.jobs import _handle_auto_job_done, _wait_for_middle_bay_full
from lib.meter.meter_manager import METERMANAGER as mm
from lib.meter.ssh_meter import SSHMeter
from lib.system import sim
from lib.sse.sse_queue_manager import SSEQM as master
from lib.system.belt_logic import boxes_to_sensors, sensors_to_boxes, step_boxes

from lib.gpio import rm, mdm

import threading
motor_thread = None
stop_event = threading.Event()
_original_rm_set_value_list = rm.set_value_list
_mock_motor_values = [rm.COAST, rm.COAST, rm.COAST]
_mock_passive_timers: dict[str, threading.Timer] = {}
_mock_physical_timers: dict[str, threading.Timer] = {}


# ================================================================
# Optional do nothings
# ================================================================
def __msg(msg): print(msg)

def _mock_null_fn(*args, **kwargs): 
    __msg("-- RUNNING mocked null fn()")
    __msg(f"    -- args -- {args}")
    __msg(f"    -- kwargs -- {kwargs}")

def _mock_null_fn_msg(name, *args, **kwargs):
    __msg(f"-- RUNNING mock {name}()")
    __msg(f"    -- args -- {args}")
    __msg(f"    -- kwargs -- {kwargs}")

# ================================================================
# Static mock meter data
# ================================================================
MOCK_MODULES = {
    "MK7_XE910": {"ver": 2209, "mod": 3, "id": 76000166},
    "KIOSK_NFC": {"ver": 2227, "mod": 0, "id": 75008793},
    "MSPM_PWR": {"ver": 2219, "mod": 2, "id": 84003495},
    "KBD_CONTROLLER": {"ver": 2217, "mod": 4, "id": 93003771},
    "EMV_CONTACT": {"ver": 26, "mod": 0, "id": 601015619},
    "COIN_SHUTTER": {"ver": 2215, "mod": 1, "id": 61003019},
    "MK7_RFID": {"ver": 2101, "mod": 0, "id": 80000066},
    "KIOSK_III": {"ver": 146, "mod": 0, "id": 57639321},
    "ESCROW_28": {"ver": 2210, "mod": 1, "id": 95000772},
    "MK7_VALIDATOR": {"ver": 2217, "mod": 2, "id": 71001241},
    "PRINTER": {"ver": 2208, "mod": 1, "id": 50003276},
    "KEY_PAD_2": {"ver": 1, "mod": 0, "id": 89003579},
}

MOCK_FIRMWARES = {
    "MK7_XE910": "2209",
    "KIOSK_NFC": "2227",
    "MSPM_PWR": "2219",
    "KBD_CONTROLLER": "2217",
    "EMV_CONTACT": "26",
    "COIN_SHUTTER": "2215",
    "MK7_RFID": "2101",
    "KIOSK_III": "146",
    "ESCROW_28": "2210",
    "MK7_VALIDATOR": "2217",
    "PRINTER": "2208",
    "KEY_PAD_2": "1",
}

MOCK_SYSTEM_VERSIONS = {"system_version": "48792", "system_sub_version": "31"}
MOCK_RESOLUTION = "800x480"
MOCK_STATUS_TEXT = "mock meter ready"
MOCK_DB_ID = 1


# ================================================================
# Runtime mock state
# ================================================================
_mock_meter_ips: set[str] = set()
_original_meter_init = SSHMeter.__init__
_original_get_ips = ip_scanner.get_ips
_original_sim_on_action = sim.on_action


# ================================================================
# Meter patch helpers
# ================================================================
def _mock_hostname(host: str):
    suffix = host.split(".")[-1]
    return f"3000{int(suffix):04d}"


def _mock_meter_init(self, host, **kwargs):
    _original_meter_init(self, host, **kwargs)
    self._Client__hostname = _mock_hostname(host)
    self._module_info_cache = MOCK_MODULES
    self._firmwares = MOCK_FIRMWARES
    self._system_versions_cache = MOCK_SYSTEM_VERSIONS
    self._module_details_cache = MOCK_MODULES
    self._SSHMeter__resolution = MOCK_RESOLUTION
    self._host = host
    self.status = "ready"
    self.results = {}
    _apply_meter_runtime_mocks(self)


def _apply_meter_runtime_mocks(meter: SSHMeter):
    meter.connect = lambda: None
    meter.close = lambda: None
    meter.force_diagnostics = lambda: None
    meter.in_diagnostics = lambda: True
    meter.is_booting = lambda: False
    meter.in_splash = lambda: False
    meter.set_brightness = lambda val: None
    meter.set_ui_mode = lambda mode: None
    meter.setup_custom_display = lambda: None
    meter.beep = lambda count=1, interval=0: None
    meter.get_meter_status_text = lambda: MOCK_STATUS_TEXT
    meter.connected = True
    meter.status = "ready"
    meter.results = {}
    meter.db_id = MOCK_DB_ID
    meter.is_mock = True
    return meter


def _next_mock_meter_ip():
    start, end = mm.address_range
    for suffix in range(end, start - 1, -1):
        host = f"{mm.base}{suffix}"
        if host not in mm.meters and host not in _mock_meter_ips:
            return host
    raise RuntimeError("No free mock meter IPs available")


def _build_meter_payload(host: str, meter: SSHMeter, status: str):
    return {
        "status": status,
        "ip": host,
        "hostname": meter.hostname,
        "meter_type": meter.meter_type,
    }


def list_mock_meters():
    return [
        _build_meter_payload(host, meter, "active")
        for host, meter in mm.meters.items()
    ]


def _mock_insert_sshmeter(meter: SSHMeter):
    meter.db_id = MOCK_DB_ID
    return (MOCK_DB_ID,)


def _mock_insert_meter_jobs(*args, **kwargs):
    _mock_null_fn_msg("insert_meter_jobs", args, kwargs)
    return []


def add_mock_meter(host: str | None = None):
    host = host or _next_mock_meter_ip()

    if host in mm.meters:
        meter = mm.meters[host]
        _mock_meter_ips.add(host)
        return _build_meter_payload(host, meter, "exists")

    _mock_meter_ips.add(host)
    mm._METERMANAGER__stale_counts.pop(host, None)
    mm._METERMANAGER__attempts.pop(host, None)
    mm._METERMANAGER__booted.pop(host, None)
    mm._METERMANAGER__splash.discard(host)
    mm.refresh()

    meter = mm.meters.get(host)
    if meter:
        return _build_meter_payload(host, meter, "added")

    raise RuntimeError(f"Failed to add mock meter {host}")


def wipe_mock_meters():
    hosts = list(_mock_meter_ips)
    threshold = getattr(mm, "_METERMANAGER__STALE_THRESHOLD", 2)
    _mock_meter_ips.clear()

    for host in hosts:
        if host in mm.meters:
            for _ in range(threshold):
                mm.stale_meter(host)

    return {"status": "wiped", "count": len(hosts), "ips": hosts}


# ================================================================
# Sim / scanner hooks
# ================================================================
def _mock_get_ips(*args, **kwargs):
    ips = set(_original_get_ips(*args, **kwargs))
    ips.update(_mock_meter_ips)
    return list(ips)


def _mock_sim_on_action(action, **kwargs):
    if action == "mock_meter":
        return add_mock_meter(kwargs.get("host")), 200
    if action == "wipe_mock_meters":
        return wipe_mock_meters(), 200
    if action == "list_meters":
        return list_mock_meters(), 200
    return _original_sim_on_action(action, **kwargs)


MOTOR_TICK_SECONDS = 0.35


def motor_worker():
    boxes = sensors_to_boxes(mdm.get_value_list())

    while not stop_event.is_set():
        motors = _mock_motor_values[:]
        boxes = step_boxes(boxes, motors)
        mdm.set_value_list(boxes_to_sensors(boxes))
        time.sleep(MOTOR_TICK_SECONDS)


def __motor_mock_moving(*args, **kwargs):
    global motor_thread, _mock_motor_values

    value = kwargs.get("value_list", [0, 0, 0])
    _mock_motor_values = value[:]
    _original_rm_set_value_list(value)

    if any(value):
        if motor_thread is None or not motor_thread.is_alive():
            stop_event.clear()
            motor_thread = threading.Thread(target=motor_worker, daemon=True)
            motor_thread.start()
    else:
        if motor_thread is not None:
            stop_event.set()
            motor_thread = None


# ================================================================
# jobs related
# ================================================================
def _broadcast_mock_progress(meter_ip: str, program: str, current: int, total: int):
    master.broadcast('progress', {
        'ip': meter_ip,
        'program': program,
        'current_cycle': current,
        'total_cycles': total,
    })


def _mock_start_physical_job(*args, **kwargs): 
    duration = 10
    _mock_null_fn_msg("start_physical_job", args, kwargs)
    meter_ip = args[0] if args else kwargs.get("meter_ip")
    if not meter_ip:
        return False, "Missing meter_ip"

    loaded, sensor_value = _wait_for_middle_bay_full(timeout_s=3.0)
    if not loaded:
        msg = f"Cannot start physical job since station M is not fully occupied; middle-bay sensors read {sensor_value:03b} (expected 111)"
        master.broadcast('notify', {'ntype': 'error', 'msg': msg})
        return False, msg

    _mock_stop_physical_job(meter_ip)
    meter = mm.get_meter(meter_ip)
    meter.status = "busy"
    master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': 'physical_cycle_all'})
    _broadcast_mock_progress(meter_ip, 'physical_cycle', 0, duration)

    def tick_physical(current_cycle: int = 1):
        if meter_ip not in _mock_physical_timers:
            return

        _broadcast_mock_progress(meter_ip, 'physical_cycle', current_cycle, duration)
        if current_cycle < duration:
            timer = threading.Timer(1.0, tick_physical, args=(current_cycle + 1,))
            _mock_physical_timers[meter_ip] = timer
            timer.start()
            return

        _mock_physical_timers.pop(meter_ip, None)
        meter.status = "ready"
        master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': ''})
        _handle_auto_job_done(meter_ip, "physical_cycle_all")

    timer = threading.Timer(1.0, tick_physical)
    _mock_physical_timers[meter_ip] = timer
    timer.start()
    return True, "started"


def _mock_stop_physical_job(meter_ip):
    _mock_null_fn_msg("stop_physical_job", (meter_ip,), {})
    timer = _mock_physical_timers.pop(meter_ip, None)
    if timer:
        timer.cancel()
    meter = mm.meters.get(meter_ip)
    if meter:
        meter.status = "ready"
    master.broadcast('status', {'ip': meter_ip, 'status': 'ready', 'current_action': ''})
    return True, "stopped"


def _mock_start_passive_job(*args, **kwargs): 
    duration = 3
    _mock_null_fn_msg("start_passive_job", args, kwargs)
    meter_ip = args[0] if args else kwargs.get("meter_ip")
    if not meter_ip:
        return False, "Missing meter_ip"

    _mock_stop_passive_job(meter_ip)
    meter = mm.get_meter(meter_ip)
    meter.status = "busy"
    master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': 'cycle_all'})
    _broadcast_mock_progress(meter_ip, 'burn-in', 0, duration)

    def tick_passive(current_cycle: int = 1):
        if meter_ip not in _mock_passive_timers:
            return

        _broadcast_mock_progress(meter_ip, 'burn-in', current_cycle, duration)
        if current_cycle < duration:
            timer = threading.Timer(1.0, tick_passive, args=(current_cycle + 1,))
            _mock_passive_timers[meter_ip] = timer
            timer.start()
            return

        _mock_passive_timers.pop(meter_ip, None)
        meter.status = "ready"
        master.broadcast('status', {'ip': meter_ip, 'status': meter.status, 'current_action': ''})
        _handle_auto_job_done(meter_ip, "cycle_all")

    timer = threading.Timer(1.0, tick_passive)
    _mock_passive_timers[meter_ip] = timer
    timer.start()
    return True, "started"


def _mock_stop_passive_job(meter_ip):
    _mock_null_fn_msg("stop_passive_job", (meter_ip,), {})
    timer = _mock_passive_timers.pop(meter_ip, None)
    if timer:
        timer.cancel()
    meter = mm.meters.get(meter_ip)
    if meter:
        meter.status = "ready"
    master.broadcast('status', {'ip': meter_ip, 'status': 'ready', 'current_action': ''})
    return True, "stopped"

# ================================================================
# the rest
# ================================================================
def _mock_blink(*args, **kwargs): _mock_null_fn_msg("blink", args, kwargs)
def _mock_blink_until_start(self, *args, **kwargs):
    _mock_null_fn_msg("blink_until_start", args, kwargs)
    self.status = "busy"
    max_duration = float(kwargs.get("max_duration", 60.0))
    on_done = kwargs.get("on_done")

    def stop_mock_blink():
        if self.status == "busy":
            self.status = "ready"
        if on_done:
            on_done()

    threading.Timer(max_duration, stop_mock_blink).start()

def _mock_blink_until_stop(self, *args, **kwargs):
    _mock_null_fn_msg("blink_until_stop", args, kwargs)
    self.status = "ready"

# ================================================================
# Patch installation
# ================================================================
def _install_patches():
    print("!!!! installing mock patches")
    strictly_virtual = True
    station_connected = False

    # stuff that is strictly virtual
    if strictly_virtual:
        patch("lib.meter.meter_manager.insert_sshmeter", _mock_insert_sshmeter).start()
        patch("ip_scanner.get_ips", _mock_get_ips).start()


        patch("lib.system.override.__motor", __motor_mock_moving).start()

        patch("lib.meter.ssh_meter.SSHMeter.blink", _mock_blink).start()
        patch("lib.meter.ssh_meter.SSHMeter.blink_until_start", _mock_blink_until_start).start()
        patch("lib.meter.ssh_meter.SSHMeter.blink_until_stop", _mock_blink_until_stop).start()

        patch("lib.meter.ssh_meter.SSHMeter.update_display_results", _mock_null_fn).start()

    # stuff that can be mocked when connected 
    if station_connected:
        pass

    # mock regardless
    patch("lib.automation.jobs.insert_meter_jobs", _mock_insert_meter_jobs).start() # no more meter job insertion
    patch("lib.meter.ssh_meter.SSHMeter.__init__", _mock_meter_init).start()        # dont need to go thru the fw grabbing?
    

    # unsorted
    patch("lib.system.station.check_robot_clear_of_conveyor", lambda: None).start()
    patch("lib.system.sim.on_action", _mock_sim_on_action).start()

    # patch("lib.meter.ssh_meter.SSHMeter.set_brightness", _mock_null_fn).start()
    # patch("lib.meter.ssh_meter.SSHMeter.beep", _mock_null_fn).start()
    
    patch("lib.system.program.start_passive_job", _mock_start_passive_job).start()
    patch("lib.system.program.stop_passive_job", _mock_stop_passive_job).start()
    patch("lib.system.program.start_physical_job", _mock_start_physical_job).start()
    patch("lib.system.program.stop_physical_job", _mock_stop_physical_job).start()
    patch("lib.automation.jobs.start_physical_job", _mock_start_physical_job).start()

_install_patches()


if __name__ == "__main__":
    from lib.automation.jobs import start_physical_job
    start_physical_job("", "")
