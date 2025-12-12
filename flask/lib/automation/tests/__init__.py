from .cycle_print import test_cycle_print
from .cycle_coin_shutter import test_cycle_coin_shutter
from .cycle_meter_ui import test_cycle_meter_ui
from .cycle_nfc import test_cycle_nfc
from .cycle_modem import test_cycle_modem
from .cycle_all import test_cycle_all
from .test_keypad import test_keypad
from .test_nfc_read import test_nfc_read
from .flash_brightness import flash_brightness as test_flash_brightness
from .test_dummy import test_dummy
from .refresh_meter import refresh_meter

from .test_robot_coin_shutter import test_robot_coin_shutter
from .test_robot_nfc_read import test_robot_nfc_read
from .test_robot_keypad import test_robot_keypad
from .physical_cycle_all import physical_cycle_all


PROGRAM_REGISTRY = {
    "cycle_print": test_cycle_print,
    "printer": test_cycle_print,    

    "cycle_coin_shutter": test_cycle_coin_shutter,
    "coin shutter": test_cycle_coin_shutter,
    
    "cycle_meter_ui": test_cycle_meter_ui,
    "screen test": test_cycle_meter_ui,

    "cycle_nfc": test_cycle_nfc,
    "nfc": test_cycle_nfc,
 
    "cycle_modem": test_cycle_modem,
    "modem": test_cycle_modem,
    
    "cycle_all": test_cycle_all,
    "all tests": test_cycle_all,

    "test_keypad": test_keypad,
    "keypad": test_keypad,

    "test_nfc_read": test_nfc_read,
    "nfc_read": test_nfc_read,

    "identify": test_flash_brightness,
    "dummy": test_dummy,
    "refresh_meter": refresh_meter,

    "test_robot_coin_shutter": test_robot_coin_shutter,
    "test_robot_nfc_read": test_robot_nfc_read,
    "test_robot_keypad": test_robot_keypad,
    "physical_cycle_all": physical_cycle_all,
}

_PROGRAM_MONITORS = {
    "cycle_print":       [("printer", {"timeout_s": 8.0})],
    "cycle_coin_shutter":[],
    "cycle_nfc":         [("nfc",     {"timeout_on_s": 6.0, "timeout_off_s": 3.0})],
    "cycle_modem":       [("modem",   {"connect_timeout_s": 25.0, "disconnect_timeout_s": 20.0})],
    "cycle_meter_ui":    [],
    "cycle_all": [
        ("nfc",     {"timeout_on_s": 6.0, "timeout_off_s": 3.0}),
        ("modem",   {"connect_timeout_s": 25.0, "disconnect_timeout_s": 20.0}),
        ("printer", {"timeout_s": 8.0}),
    ],
    # "test_keypad":       [("keypad",  {"inactivity_timeout_s": 15.0, "layouts": ["1x6"], "count": 1})],
    "test_keypad":       [("keypad",  {"inactivity_timeout_s": 15.0, "count": 1})],
    "test_nfc_read":     [("nfc",     {"timeout_on_s": 6.0, "timeout_off_s": 3.0})],
    "test_robot_nfc_read":  [("nfc",  {"timeout_on_s": 6.0, "timeout_off_s": 3.0})],
    "test_robot_keypad":    [("robot_keypad",  {"buttons": ["0", "1", "2", "3"]})],
    "physical_cycle_all":   [
        ("nfc",     {"timeout_on_s": 6.0, "timeout_off_s": 3.0}),
        ("robot_keypad", {"inactivity_timeout_s": 40})
    ]
}

def _build_alias_index(registry):
    func_to_canon = {}
    for name, fn in registry.items():
        if name.startswith("cycle_") and fn not in func_to_canon:
            func_to_canon[fn] = name
    for name, fn in registry.items():
        func_to_canon.setdefault(fn, name)
    return {name: func_to_canon[fn] for name, fn in registry.items()}

_ALIAS_TO_CANON = _build_alias_index(PROGRAM_REGISTRY)

def get_monitors(program_name: str):
    canon = _ALIAS_TO_CANON.get(program_name, program_name)
    return _PROGRAM_MONITORS.get(canon, [])


__all__ = ["PROGRAM_REGISTRY", "get_monitors"]