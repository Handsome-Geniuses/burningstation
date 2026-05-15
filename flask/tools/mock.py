from unittest.mock import patch
import ip_scanner
import time

from lib.meter.meter_manager import METERMANAGER as mm
from lib.meter.ssh_meter import SSHMeter
from lib.system import sim


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

MOCK_HOSTNAME = "30001189"
MOCK_SYSTEM_VERSIONS = {"system_version": "48792", "system_sub_version": "31"}
MOCK_RESOLUTION = "800x480"
MOCK_STATUS_TEXT = "mock meter ready"
MOCK_DB_ID = -1


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
def _mock_meter_init(self, host, **kwargs):
    _original_meter_init(self, host, **kwargs)
    self._Client__hostname = MOCK_HOSTNAME
    self._module_info_cache = MOCK_MODULES
    self._firmwares = MOCK_FIRMWARES
    self._system_versions_cache = MOCK_SYSTEM_VERSIONS
    self._module_details_cache = MOCK_MODULES
    self._SSHMeter__resolution = MOCK_RESOLUTION
    self._host = host
    self.status = "ready"
    self.results = {}


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


def add_mock_meter(host: str | None = None):
    host = host or _next_mock_meter_ip()

    if host in mm.meters:
        meter = mm.meters[host]
        _mock_meter_ips.add(host)
        return _build_meter_payload(host, meter, "exists")

    meter = _apply_meter_runtime_mocks(SSHMeter(host))
    mm.meters[host] = meter
    mm._METERMANAGER__meters.add(host)
    mm._METERMANAGER__splash.discard(host)
    mm._METERMANAGER__booted.pop(host, None)
    mm._METERMANAGER__attempts.pop(host, None)
    mm._METERMANAGER__stale_counts.pop(host, None)
    _mock_meter_ips.add(host)

    return _build_meter_payload(host, meter, "added")


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
    if action == "list_meters":
        return list_mock_meters(), 200
    return _original_sim_on_action(action, **kwargs)


# ================================================================
# Optional local test helper
# ================================================================
def _mock_start_physical_job(meter_up, buttons=None):
    print("[👽 mock_start_physical_job] starting ...")
    for _ in range(3):
        time.sleep(1)
        print("[👽 mock_start_physical_job] working ...")
    print("[👽 mock_start_physical_job] ... DONE!")


# ================================================================
# Patch installation
# ================================================================
def _install_patches():
    patch("lib.meter.ssh_meter.SSHMeter.__init__", _mock_meter_init).start()
    patch("ip_scanner.get_ips", _mock_get_ips).start()
    patch("lib.system.station.check_robot_clear_of_conveyor", lambda: None).start()
    patch("lib.system.sim.on_action", _mock_sim_on_action).start()


_install_patches()


if __name__ == "__main__":
    from lib.automation.jobs import start_physical_job

    start_physical_job("", "")
