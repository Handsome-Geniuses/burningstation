from lib.gpio.gpio_setup import tower_interface
from lib.system.states import states
from lib.sse.sse_queue_manager import SSEQM, key_payload

pcfio, r, y, g, buzzer = tower_interface

def __broadcast_change():
    """Broadcast the current tower state via SSE."""
    SSEQM.broadcast("state", key_payload("tower", states['tower']))

def red(state: bool):
    """Activate or deactivate the tower red light."""
    if states['tower'][0] != state:
        pcfio.set_state(r, state)
        states['tower'][0] = state
        __broadcast_change()

def yellow(state: bool):
    """Activate or deactivate the tower yellow light."""
    if states['tower'][1] != state:
        pcfio.set_state(y, state)
        states['tower'][1] = state
        __broadcast_change()

def green(state: bool):
    """Activate or deactivate the tower green light."""
    if states['tower'][2] != state:
        pcfio.set_state(g, state)
        states['tower'][2] = state
        __broadcast_change()

def buzz(state: bool):
    """Activate or deactivate the tower buzzer."""
    if states['tower'][3] != state:
        buzzer.state = state
        states['tower'][3] = state
        __broadcast_change()

def get_value_list() -> list[int]:
    """Return tower outputs as list of 4 booleans [R, G, B, Buzzer]."""
    byte = pcfio.read_byte()
    return [
        bool((byte >> r) & 0b1),
        bool((byte >> y) & 0b1),
        bool((byte >> g) & 0b1),
        bool(buzzer.state)
    ]

__all__ = ['red', 'yellow', 'green', 'buzz', 'get_value_list']