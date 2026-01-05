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

EXPECTED_MIN_INCREASE_mA = 100   # adjust based on your floodlight strength and panel size
EXPECTED_DROP_TOLERANCE_mA = 30  # allow some hysteresis/slow decay
MAX_BASELINE_DRIFT_mA = 30       # how much off-to-off can vary naturally

def _parse_power_status_line(res: str) -> Dict:
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
            print(f"Warning: Skipping malformed key-value pair: '{pair}'")

    return {
        'datetime_str': datetime_str,
        'hostname': hostname,
        'power_status_raw': full_power_line,
        'power_data': power_data
    }

def get_latest_power_status(meter: SSHMeter):
    cmd = (
        "journalctl -u MS3_Platform.service -n 250 --no-pager | "
        "grep 'Meter:sProcessIPSBusMessage:' | "
        "grep 'Power status:' | "
        "tail -1"
    )
    res = meter.cli(cmd)
    parsed = _parse_power_status_line(res)
    # for k,v in parsed.items():
    #     print(f"{k}: {v}")

    return parsed

def get_numeric_value(val: str) -> float:
    """Extract number from value like '9337mV' -> 9337.0 or '25C' -> 25.0"""
    # Remove units (mV, mA, C, mAH, etc.)
    numeric_part = ''.join(c for c in val if c.isdigit() or c in '.-')
    return float(numeric_part)



def test_solar(meter: SSHMeter, shared: SharedState = None, **kwargs):
    func_name = inspect.currentframe().f_code.co_name

    baseline = get_latest_power_status(meter)
    charge_off_1 = get_numeric_value(baseline["power_data"]["ChargeCurrent"])
    print(f"\n{baseline['power_data']}")
    print(f"charge_off_1: {charge_off_1}")
    time.sleep(6)

    lm.lamp(0, True, 100)
    lm.lamp(1, True, 100)
    time.sleep(8)

    illuminated = get_latest_power_status(meter)
    charge_on = get_numeric_value(illuminated["power_data"]["ChargeCurrent"])
    print(f"\n{illuminated['power_data']}")
    print(f"charge_on: {charge_on}")

    # Recovery (lights OFF again)
    lm.lamp(0, False, 100)
    lm.lamp(1, False, 100)
    time.sleep(8)

    recovery = get_latest_power_status(meter)
    charge_off_2 = get_numeric_value(recovery["power_data"]["ChargeCurrent"])
    print(f"\n{recovery['power_data']}")
    print(f"charge_off_2: {charge_off_2}")

    # Must significantly increase when light is on
    if charge_on <= charge_off_1 + EXPECTED_MIN_INCREASE_mA:
        raise StopAutomation("ChargeCurrent did not increase enough when light turned on")

    # Must drop back close to baseline when light removed
    if charge_off_2 > charge_on - EXPECTED_DROP_TOLERANCE_mA:
        raise StopAutomation("ChargeCurrent did not decrease after light turned off")

    # # Optional: recovery should be similar to initial baseline
    # if abs(charge_off_2 - charge_off_1) > MAX_BASELINE_DRIFT_mA:
    #     raise StopAutomation("Baseline drifted — possible temperature effect or load change")



if __name__ == "__main__":
    try:
        meter = SSHMeter("192.168.169.33")
        # meter = SSHMeter("192.168.69.110")
        meter.connect()
        
        power_status = get_latest_power_status(meter)
        print(power_status["power_data"]["ChargeCurrent"])

        # test_solar(meter)


    except Exception as e:
        print(f"error: {e}")
        pass
    finally:
        try: meter.close()
        except: pass

