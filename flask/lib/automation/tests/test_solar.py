import time
import re
import inspect
from typing import Dict, List, Optional, Union

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
# from lib.gpio import lm
from lib.system import lm


EXPECTED_MIN_INCREASE_mA_1 = 50
EXPECTED_MIN_INCREASE_mA_2 = 50
EXPECTED_DROP_TOLERANCE_mA_1 = 30
EXPECTED_DROP_TOLERANCE_mA_2 = 30
POWER_STATUS_WINDOW_SIZE = 100
POWER_STATUS_POLL_SECONDS = 3
POWER_STATUS_WAIT_TIMEOUT_SECONDS = 60


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


def _parse_power_status_lines(res: str, shared: SharedState) -> List[Dict]:
    parsed_lines: List[Dict] = []
    for line in res.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed_lines.append(_parse_power_status_line(line, shared))
        except ValueError as exc:
            shared.log(f"Warning: failed to parse power status line '{line}': {exc}")
    return parsed_lines


def get_latest_power_status(
    meter: SSHMeter,
    shared: SharedState,
    count: int = 1,
    window_size: int = POWER_STATUS_WINDOW_SIZE,
    log_result: bool = True,
    log_missing: bool = True,
) -> Optional[Union[Dict, List[Dict]]]:
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")

    cmd = (
        f"journalctl -u MS3_Platform.service -n {window_size} --no-pager | "
        "grep 'Meter:sProcessIPSBusMessage:' | "
        "grep 'Power status:' | "
        f"tail -n {count}"
    )
    res = meter.cli(cmd)
    parsed_statuses = _parse_power_status_lines(res, shared)
    if not parsed_statuses:
        if log_missing:
            shared.log(
                f"No power status found in last {window_size} journal lines "
                f"(requested count={count})"
            )
        return None

    if count == 1:
        parsed = parsed_statuses[-1]
        if log_result:
            shared.log(f"Latest power status: {parsed}")
        return parsed

    parsed = parsed_statuses[-count:]
    if log_result:
        shared.log(f"Latest {len(parsed)} power statuses: {parsed}")
    return parsed


def _power_status_identity(status: Optional[Dict]) -> Optional[str]:
    if not status:
        return None
    return f"{status.get('datetime_str', '')}|{status.get('power_status_raw', '')}"


def _sleep_with_stop(shared: SharedState, seconds: float, poll_interval: float = 0.25) -> None:
    deadline = time.time() + max(0.0, seconds)
    while True:
        check_stop_event(shared)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(poll_interval, remaining))


def wait_for_fresh_power_status(
    meter: SSHMeter,
    shared: SharedState,
    previous_status: Optional[Dict],
    reason: str,
    timeout_s: float = POWER_STATUS_WAIT_TIMEOUT_SECONDS,
    poll_s: float = POWER_STATUS_POLL_SECONDS,
    window_size: int = POWER_STATUS_WINDOW_SIZE,
) -> Dict:
    previous_identity = _power_status_identity(previous_status)
    previous_datetime = previous_status.get("datetime_str") if previous_status else None
    shared.log(
        "Waiting for fresh power status after "
        f"{reason}. previous_datetime_str={previous_datetime!r}, "
        f"window_size={window_size}, poll_s={poll_s}, timeout_s={timeout_s}"
    )

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        latest_status = get_latest_power_status(
            meter,
            shared,
            count=1,
            window_size=window_size,
            log_result=False,
            log_missing=False,
        )
        if latest_status is not None:
            latest_identity = _power_status_identity(latest_status)
            if previous_identity is None or latest_identity != previous_identity:
                shared.log(f"Fresh power status after {reason}: {latest_status}")
                return latest_status
        _sleep_with_stop(shared, poll_s)

    raise StopAutomation(
        "Timed out waiting for a fresh power status after "
        f"{reason} (timeout={timeout_s}s, window_size={window_size})"
    )


def get_numeric_value(val: str) -> float:
    """Extract number from value like '9337mV' -> 9337.0 or '25C' -> 25.0"""
    # Remove units (mV, mA, C, mAH, etc.)
    numeric_part = ''.join(c for c in val if c.isdigit() or c in '.-')
    return float(numeric_part)


def test_solar(meter: SSHMeter, shared: SharedState, **kwargs):
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, func_name, 1, 1)

    meter.set_ui_mode("banner") # shouldnt matter if kwargs.charuco_frame is None bc robot isnt used
    meter.goto_power()

    curr = lm.get_value_list()
    if curr[0] or curr[1]:
        lm.lamp(0, False, 100)
        lm.lamp(1, False, 100)

    latest_seen_status = get_latest_power_status(meter, shared)
    baseline = wait_for_fresh_power_status(
        meter,
        shared,
        latest_seen_status,
        "capturing baseline with both lamps off",
    )
    baseline_power = baseline["power_data"]
    charge_off = get_numeric_value(baseline_power["ChargeCurrent"])
    battery_voltage = get_numeric_value(baseline_power["BatteryVoltage"])
    shared.log(f"charge_off_1: {charge_off}")
    shared.log(f"battery_voltage: {battery_voltage}")

    # ---- Lamp 1 ON/OFF (rear) ----
    _sleep_with_stop(shared, 1)
    lm.lamp(0, True, 100)
    rear_illuminated = wait_for_fresh_power_status(
        meter,
        shared,
        baseline,
        "turning lamp 1 on",
    )
    charge_on_l1 = get_numeric_value(rear_illuminated["power_data"]["ChargeCurrent"])
    shared.log(f"charge_on_l1: {charge_on_l1}")

    lm.lamp(0, False, 100)
    delta_l1 = charge_on_l1 - charge_off

    # ---- Lamp 2 ON/OFF (top) ----
    _sleep_with_stop(shared, 1)
    lm.lamp(1, True, 100)
    top_illuminated = wait_for_fresh_power_status(
        meter,
        shared,
        rear_illuminated,
        "turning lamp 2 on",
    )
    top_power = top_illuminated["power_data"]
    charge_on_l2 = get_numeric_value(top_power["ChargeCurrent"])
    solar_voltage = get_numeric_value(top_power["InputVoltage"]) # idk if this is the solar voltage value they want or not
    shared.log(f"charge_on_l2: {charge_on_l2}")
    shared.log(f"solar_voltage: {solar_voltage}")

    # both off
    lm.lamp(1, False, 100)
    recovery = wait_for_fresh_power_status(
        meter,
        shared,
        top_illuminated,
        "turning lamp 2 off",
    )
    recovery_power = recovery["power_data"]
    charge_off_l1 = get_numeric_value(recovery_power["ChargeCurrent"])
    charge_off_l2 = charge_off_l1
    shared.log(f"charge_off_l2: {charge_off_l2}")
    shared.log(f"charge_off_l1: {charge_off_l1}")

    delta_l2 = charge_on_l2 - charge_off
    solar_data = {
        "battery mV": battery_voltage,
        "rear_mA": delta_l1,
        "top_mA": delta_l2,
        "solar mV": solar_voltage,
    }
    shared.device_meta["solar"] = solar_data

    # check
    if charge_on_l1 <= charge_off + EXPECTED_MIN_INCREASE_mA_1:
        s = f"ChargeCurrent did not increase enough when lamp 1 turned on. {charge_on_l1} --> {charge_off}"
        shared.log(s)
        raise StopAutomation(s)
    if charge_off_l1 > charge_on_l1 - EXPECTED_DROP_TOLERANCE_mA_1:
        s = f"ChargeCurrent did not decrease after lamp 1 turned off. {charge_off_l1} --> {charge_on_l1}"
        shared.log(s)
        raise StopAutomation(s)
    if charge_on_l2 <= charge_off + EXPECTED_MIN_INCREASE_mA_2:
        s = f"ChargeCurrent did not increase enough when lamp 2 turned on. {charge_on_l2} --> {charge_off}"
        shared.log(s)
        raise StopAutomation(s)
    if charge_off_l2 > charge_on_l2 - EXPECTED_DROP_TOLERANCE_mA_2:
        s = f"ChargeCurrent did not decrease after lamp 2 turned off. {charge_off_l2} --> {charge_on_l2}"
        shared.log(s)
        raise StopAutomation(s)
