# ====================================================
# manual override controls! be careful
# ====================================================

from lib.gpio import rm
from lib.hardware import hardware

def __motor(**kwargs):
    hardware.require("motor_control")
    value = kwargs.get("value_list", [0,0,0])
    rm.set_value_list(value)


def on_action(action, **kwargs):
    res = None
    if action=="motor": __motor(**kwargs)

    return res if res is not None else ("", 200)


__all__ = ['on_action']
