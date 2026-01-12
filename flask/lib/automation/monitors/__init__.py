import inspect

from lib.automation.shared_state import SharedState
from .printer import PrinterMonitor
from .nfc import NFCMonitor
from .modem import ModemMonitor
from .keypad import KeypadMonitor
from .robot_keypad import RobotKeypadMonitor


REGISTRY = {
    "printer": PrinterMonitor,
    "nfc": NFCMonitor,
    "modem": ModemMonitor,
    "keypad": KeypadMonitor,
    "nfc_read": NFCMonitor,
    "robot_keypad": RobotKeypadMonitor,
}


def create_monitor(kind: str, shared: SharedState, **kwargs):
    try:
        Mod = REGISTRY[kind]
    except KeyError:
        raise ValueError(f"Unknown device '{kind}'")
    
    return Mod(shared=shared, **kwargs)