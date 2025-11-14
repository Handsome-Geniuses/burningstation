# ====================================================
# 
# ====================================================
import threading
import time
from lib.gpio import HWGPIO, HWGPIO_MONITOR, emergency
from asyncdec import AsyncManager, async_fire_and_forget

am_program = AsyncManager("am_program")
def emergency_event(p:HWGPIO):
    if p.state: am_program.emergency_stop()
    else: am_program.emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,emergency_event)


@am_program.operation(timeout=10)
def some_program():
    pass


def on_action(action, **kwargs):
    res = None
    return res if res is not None else ("", 200)

__all__ = ['on_action']

