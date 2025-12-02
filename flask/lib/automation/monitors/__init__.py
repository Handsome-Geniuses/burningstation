from .printer import PrinterMonitor
from .nfc import NFCMonitor
from .modem import ModemMonitor
from .keypad import KeypadMonitor


REGISTRY = {
    "printer": PrinterMonitor,
    "nfc": NFCMonitor,
    "modem": ModemMonitor,
    "keypad": KeypadMonitor,
    "nfc_read": NFCMonitor,
}


def create_monitor(kind: str, **kwargs):
    try:
        Mod = REGISTRY[kind]
    except KeyError:
        raise ValueError(f"Unknown device '{kind}'")
    return Mod(**kwargs)
