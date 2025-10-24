from lib.gpio import *
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.system.states import states, update
from typing import Callable, Any

def event_builder(key: str, value_fn: Callable[..., Any], extra_fn: Callable=lambda:None) -> Callable:
    def handler(p: HWGPIO):
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
meter_detection_event = event_builder("mds", lambda p: mdm.get_state())
HWGPIO_MONITOR.add_listener(pcfio1.intgpio, meter_detection_event)
HWGPIO_MONITOR.add_listener(pcfio2.intgpio, meter_detection_event)


