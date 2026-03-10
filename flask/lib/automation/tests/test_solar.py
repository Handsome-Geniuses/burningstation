import os
import time
import re
import inspect
from datetime import datetime
from typing import Dict, Tuple

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
# from lib.gpio import lm
from lib.system import lm


EXPECTED_MIN_INCREASE_mA = 15
EXPECTED_MIN_INCREASE_mA_1 = 50
EXPECTED_MIN_INCREASE_mA_2 = 50
EXPECTED_DROP_TOLERANCE_mA = 30
EXPECTED_DROP_TOLERANCE_mA_1 = 30
EXPECTED_DROP_TOLERANCE_mA_2 = 30
LAMP_ON_DELAY = 8
LAMP_OFF_DELAY = 8

def _parse_power_status_line(res: str, shared: SharedState) -> Dict:
    """
    Parses a journalctl power status log line into structured data.
    
    Example input:
    "Dec 16 11:52:04 30002432 MS3[528]: Meter:sProcessIPSBusMessage:1938: Power status: version=3, ..."
    """
    res = res.strip()
    if not res:
        raise ValueError("Empty log line")

    if ": " not in res:
        raise ValueError(f"Log line does not contain ': ': {res}")
    
    header, message = res.split(": ", 1)
    header_parts = header.split()
    # print(f'header_parts: {header_parts}')

    if len(header_parts) < 4:
        raise ValueError(f"Unexpected header format: {header}")

    datetime_str = " ".join(header_parts[:3])  # "Dec 16 11:52:04"
    hostname = header_parts[3]                 # "30002432"

    if "Power status:" not in message:
        raise ValueError("No 'Power status:' found in message")

    power_status_raw = message.split("Power status:", 1)[1].strip()
    full_power_line = "Power status: " + power_status_raw

    fixed_power_status = re.sub(
        r'([a-zA-Z0-9]+)=([^,=\s]+)\s+([a-zA-Z0-9]+)=' ,
        r'\1=\2, \3=',
        power_status_raw
    )
    pairs = fixed_power_status.split(', ')

    power_data = {}
    for pair in pairs:
        if '=' in pair:
            key, value = pair.split('=', 1)
            power_data[key] = value
        else:
            shared.log(f"Warning: Skipping malformed key-value pair: '{pair}'")

    return {
        'datetime_str': datetime_str,
        'hostname': hostname,
        'power_status_raw': full_power_line,
        'power_data': power_data
    }

def get_latest_power_status(meter: SSHMeter, shared: SharedState):
    cmd = (
        "journalctl -u MS3_Platform.service -n 250 --no-pager | "
        "grep 'Meter:sProcessIPSBusMessage:' | "
        "grep 'Power status:' | "
        "tail -1"
    )
    res = meter.cli(cmd)
    parsed = _parse_power_status_line(res, shared)
    shared.log(f"Latest power status: {parsed}")
    # for k,v in parsed.items(): print(f"{k}: {v}")

    return parsed

def get_numeric_value(val: str) -> float:
    """Extract number from value like '9337mV' -> 9337.0 or '25C' -> 25.0"""
    # Remove units (mV, mA, C, mAH, etc.)
    numeric_part = ''.join(c for c in val if c.isdigit() or c in '.-')
    return float(numeric_part)


def test_solar(meter: SSHMeter, shared: SharedState, **kwargs):
    # TODO: Need to also check charge/solar voltage or something
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, func_name, 1, 1)

    # ensure off and get baseline
    curr = lm.get_value_list()
    if curr[0] or curr[1]:
        lm.lamp(0, False, 100)
        lm.lamp(1, False, 100)
        time.sleep(LAMP_OFF_DELAY)
    baseline = get_latest_power_status(meter, shared)
    charge_off = get_numeric_value(baseline["power_data"]["ChargeCurrent"])
    shared.log(f"charge_off_1: {charge_off}")


    # ---- Lamp 1 (rear) ----
    # on
    time.sleep(1)
    lm.lamp(0, True, 100)
    time.sleep(LAMP_ON_DELAY)
    illuminated = get_latest_power_status(meter, shared)
    charge_on_l1 = get_numeric_value(illuminated["power_data"]["ChargeCurrent"])
    shared.log(f"charge_on_l1: {charge_on_l1}")

    # off
    lm.lamp(0, False, 100)
    time.sleep(LAMP_OFF_DELAY)
    recovery = get_latest_power_status(meter, shared)
    charge_off_l1 = get_numeric_value(recovery["power_data"]["ChargeCurrent"])
    shared.log(f"charge_off_l1: {charge_off_l1}")

    delta_l1 = charge_on_l1 - charge_off
    shared.device_meta["solar"] = f"rear {delta_l1:.0f} mA"

    # check
    if charge_on_l1 <= charge_off + EXPECTED_MIN_INCREASE_mA_1:
        s = f"ChargeCurrent did not increase enough when lamp 1 turned on. {charge_on_l1} --> {charge_off}"
        shared.log(s)
        raise StopAutomation(s)
    if charge_off_l1 > charge_on_l1 - EXPECTED_DROP_TOLERANCE_mA_1:
        s = f"ChargeCurrent did not decrease after lamp 1 turned off. {charge_off_l1} --> {charge_on_l1}"
        shared.log(s)
        raise StopAutomation(s)

    # ---- Lamp 2 (top) ----
    # on
    time.sleep(1)
    lm.lamp(1, True, 100)
    time.sleep(LAMP_ON_DELAY)
    illuminated = get_latest_power_status(meter, shared)
    charge_on_l2 = get_numeric_value(illuminated["power_data"]["ChargeCurrent"])
    shared.log(f"charge_on_l2: {charge_on_l2}")

    # off
    lm.lamp(1, False, 100)
    time.sleep(LAMP_OFF_DELAY)
    recovery = get_latest_power_status(meter, shared)
    charge_off_l2 = get_numeric_value(recovery["power_data"]["ChargeCurrent"])
    shared.log(f"charge_off_l2: {charge_off_l2}")

    delta_l2 = charge_on_l2 - charge_off
    shared.device_meta["solar"] = f"rear {delta_l1:.0f} mA, top {delta_l2:.0f} mA"

    #check
    if charge_on_l2 <= charge_off + EXPECTED_MIN_INCREASE_mA_2:
        s = f"ChargeCurrent did not increase enough when lamp 2 turned on. {charge_on_l2} --> {charge_off}"
        shared.log(s)
        raise StopAutomation(s)
    if charge_off_l2 > charge_on_l2 - EXPECTED_DROP_TOLERANCE_mA_2:
        s = f"ChargeCurrent did not decrease after lamp 2 turned off. {charge_off_l2} --> {charge_on_l2}"
        shared.log(s)
        raise StopAutomation(s)
