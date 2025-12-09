import inspect

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


def create_monitor(kind: str, shared=None, **kwargs):
    try:
        Mod = REGISTRY[kind]
    except KeyError:
        raise ValueError(f"Unknown device '{kind}'")
    
    init_args = {}
    if "shared" in inspect.getfullargspec(Mod.__init__).args:
        init_args["shared"] = shared

    return Mod(**init_args, **kwargs)