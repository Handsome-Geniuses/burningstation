from lib.gpio import *
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.system.states import states, update
from typing import Callable, Any
import time
from lib.utils import secrets

def event_builder(key: str, value_fn: Callable[..., Any], extra_fn: Callable=lambda:None) -> Callable:
    def handler(p: HWGPIO):
        if secrets.VERBOSE: print(f"[listener] p{p.gpio} -- {p.state}")
        value = value_fn(p)
        if states.get(key, None) == value:
            return
        states.update({key: value})
        extra_fn()
        SSEQM.broadcast("state", key_payload(key, value))
    return handler

# =============================================================
# emergency!
# =============================================================
def extra_emergency():
    rm.set_value(0)
    states['running'] = False
HWGPIO_MONITOR.add_listener(emergency, event_builder("emergency", lambda p: p.state, extra_emergency))

# =============================================================
# roller manager event
# =============================================================
roller_motor_event = event_builder("motors", lambda p: rm.get_value_list())
HWGPIO_MONITOR.add_listener(pcfio2.intgpio, roller_motor_event)

# =============================================================
# meter detection manager event. need 2 cause... 2 pcf
# =============================================================
# meter_detection_event = event_builder("mds", lambda p: mdm.get_state())
_meter_detection_event = event_builder("mds", lambda p: mdm.get_state())
def meter_detection_event(p:HWGPIO):
    # pcfio1.write_byte(pcfio1.read_byte())
    # pcfio2.write_byte(pcfio2.read_byte())
    pcfio1.write_byte(0xff)
    pcfio2.write_byte(0xff)
    # pcfio3.write_byte(0xff)
    time.sleep(0.05)
    pcfio1.write_byte(0)
    pcfio2.write_byte(0)
    # pcfio3.write_byte(0)
    _meter_detection_event(p) 



HWGPIO_MONITOR.add_listener(pcfio1.intgpio, meter_detection_event)
HWGPIO_MONITOR.add_listener(pcfio2.intgpio, meter_detection_event)


# =============================================================
# hmm experiment time 
# =============================================================
# def experimentation(p:HWGPIO):



