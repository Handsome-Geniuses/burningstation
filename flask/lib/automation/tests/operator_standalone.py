"""Standalone operator tests with uniform timing and lightweight simulation."""
from functools import partial
import time

from lib.automation.helpers import check_stop_event
from .operator_cycle_all import OPERATOR_TESTS, _run_operator_test

OPERATOR_PROGRAMS = {
    "operator_keypad": "keypad",
    "operator_screen_cycle": "screen_test",
    "operator_coins": "coins",
    "operator_touchscreen": "touchscreen",
    "operator_display_brightness": "display_brightness",
    "operator_nfc_tap": "contactless",
    "operator_card_reader": "card_reader",
}


def run_operator_standalone(meter, shared, device, **kwargs):
    started = time.monotonic()
    error = ""
    try:
        check_stop_event(shared)
        if getattr(meter, "is_mock", False) and device != "keypad":
            shared.device_results[device] = "running"
            shared.log(f"Mock operator {device}: simulated run")
            for step in range(10):
                check_stop_event(shared)
                shared.broadcast_progress(meter.host, shared.current_program, step, 10)
                time.sleep(0.1)
            check_stop_event(shared)
            shared.device_results[device] = "pass"
            shared.device_meta.setdefault(device, {})["mock"] = True
            shared.broadcast_progress(meter.host, shared.current_program, 10, 10)
        else:
            _, test_func, defaults = next(row for row in OPERATOR_TESTS if row[0] == device)
            _run_operator_test(meter, shared, device, test_func, {**defaults, **kwargs})
            check_stop_event(shared)
    except Exception as exc:
        error = str(exc)
        shared.device_results[device] = "fail"
        raise
    finally:
        duration = round(time.monotonic() - started, 3)
        result = shared.device_results.get(device, "fail")
        shared.device_meta.setdefault(device, {}).update(
            duration_s=duration, result=result,
        )
        if error:
            shared.device_meta[device]["error"] = error
        shared.extras["duration_s"] = duration
        shared.log(f"Operator {device}: {result}; duration_s={duration}; error={error}")


STANDALONE_TESTS = {
    name: partial(run_operator_standalone, device=device)
    for name, device in OPERATOR_PROGRAMS.items()
}
