from pigpiod import HWGPIO
from lib.gpio.gpio_setup import pcfio_tower, pin_buzzer
from lib.system.states import states
from lib.sse.sse_queue_manager import SSEQM, key_payload

# pcfio, r, y, g, buzzer = tower_interface
pcfio, r, y, g = pcfio_tower
buzzer = HWGPIO(pin_buzzer, 'out')

def __broadcast_change():
    """Broadcast the current tower state via SSE."""
    SSEQM.broadcast("state", key_payload("tower", states['tower']))

def red(state: bool):
    """Activate or deactivate the tower red light."""
    state = bool(state)
    if states['tower'][0] != state:
        pcfio.set_state(r, not state)  # Inverted for active-low hardware
        states['tower'][0] = state     # Logical state remains intuitive
        __broadcast_change()

def yellow(state: bool):
    """Activate or deactivate the tower yellow light."""
    state = bool(state)
    if states['tower'][1] != state:
        pcfio.set_state(y, not state)  # Inverted for active-low hardware
        states['tower'][1] = state     # Logical state remains intuitive
        __broadcast_change()

def green(state: bool):
    """Activate or deactivate the tower green light."""
    state = bool(state)
    if states['tower'][2] != state:
        pcfio.set_state(g, not state)  # Inverted for active-low hardware
        states['tower'][2] = state     # Logical state remains intuitive
        __broadcast_change()

def buzz(state: bool):
    """Activate or deactivate the tower buzzer."""
    state = bool(state)
    if states['tower'][3] != state:
        buzzer.state = state           # Assuming buzzer is active-high
        states['tower'][3] = state
        __broadcast_change()

def get_value_list() -> list[int]:
    """Return tower outputs as list of 4 booleans [R, Y, G, Buzzer]."""
    byte = pcfio.read_byte()
    return [
        not bool((byte >> r) & 0b1),   # Invert read for active-low R
        not bool((byte >> y) & 0b1),   # Invert read for active-low Y
        not bool((byte >> g) & 0b1),   # Invert read for active-low G
        bool(buzzer.state)             # Buzzer read normally
    ]

def set_value_list(values: list[bool] | list[int]):
    """
    Set all tower outputs at once by calling the existing functions.
    
    values: [R, Y, G, Buzzer]
    """
    if len(values) != 4:
        raise ValueError("Expected a list of 4 values: [R, Y, G, Buzzer]")

    red(values[0])
    yellow(values[1])
    green(values[2])
    buzz(values[3])

__all__ = ['red', 'yellow', 'green', 'buzz', 'get_value_list', 'set_value_list']