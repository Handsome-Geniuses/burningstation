from lib.gpio.gpio_setup import lamp_interface
from lib.system.states import states
from lib.sse.sse_queue_manager import SSEQM, key_payload

pcfio, l1, l2 = lamp_interface

def __broadcast_change():
    """Broadcast the current tower state via SSE."""
    SSEQM.broadcast("state", key_payload("lamp", states['lamp']))


def lamp1(state: bool):
    """Activate or deactivate lamp 1."""
    if states['lamp'][0] != state:
        pcfio.set_state(l1, state)
        states['lamp'][0] = state
        __broadcast_change()
def lamp2(state: bool):
    """Activate or deactivate lamp 2."""
    if states['lamp'][1] != state:
        pcfio.set_state(l2, state)
        states['lamp'][1] = state
        __broadcast_change()

def get_value_list() -> list[int]:
    """Return lamp outputs as list of 2 booleans [Lamp1, Lamp2]."""
    byte = pcfio.read_byte()
    return [
        bool((byte >> l1) & 0b1),
        bool((byte >> l2) & 0b1),
    ]

