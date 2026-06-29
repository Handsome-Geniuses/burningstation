import random
import threading

from lib.gpio import *
from lib.sse import ask_clients
from lib.system import program
import lib.system.station as station
import lib.system.override as override
from lib.system.states import states
from lib.system.belt_logic import (
    BAY_STARTS,
    boxes_are_valid,
    boxes_to_sensors,
    move_box_frames,
    move_is_clear,
    move_many_frames,
    sensors_to_boxes,
)
from lib.utils import packer, secrets
from prettyprint import STYLE, prettyprint as print

_sim_lock = threading.Lock()
_sim_running = False
_sim_emergency_stop = False


"""
# Set bit n
value |= (1 << n)

# Clear bit n
value &= ~(1 << n)

# Toggle bit n
value ^= (1 << n)

# Check if bit n is set
is_set = bool(value & (1 << n))
"""



def sim_operation(delay: float = 1.0):
    """Decorator that manages threading, _sim_lock, and _sim_running for simulation operations"""

    def decorator(fn):
        def wrapper(**kwargs):
            global _sim_running
            global _sim_lock
            global _sim_emergency_stop
            
            with _sim_lock:
                if _sim_emergency_stop:
                    print("🕯️ [sim] emergency stop active!", fg="#ffaa00")
                    return "Emergency stop active", 500
                if _sim_running:
                    return "Already running", 409
                _sim_running = True

            def run_steps():
                global _sim_running
                global _sim_lock
                global _sim_emergency_stop
                try:
                    fn(delay=delay, **kwargs)
                finally:
                    with _sim_lock:
                        _sim_running = False

            # Start in background thread
            threading.Thread(target=run_steps, daemon=True).start()
            return "", 200

        return wrapper

    return decorator

def execute_steps(step_actions: dict, **kwargs):
    """Execute a dictionary of steps with delays between them"""
    global _sim_emergency_stop
    delay = kwargs.get('delay', 1.0)
    
    def run_step(i=0):
        if _sim_emergency_stop:
            return
        if i in step_actions:
            step_actions[i]()
        if i < max(step_actions.keys()) and not _sim_emergency_stop:
            threading.Timer(delay, lambda i=i: run_step(i + 1)).start()

    run_step(0)
    return "", 200

def sim_emergency_stop():
    """Activate emergency stop - prevents new sim operations from starting"""
    global _sim_emergency_stop
    global _sim_running
    with _sim_lock:
        _sim_emergency_stop = True
        _sim_running = False
    print("🕯️ [sim] emergency stop activated!", fg="#ffaa00")

def sim_emergency_reset():
    """Reset emergency stop flag - call this to allow sim operations again"""
    global _sim_emergency_stop
    global _sim_running
    with _sim_lock:
        _sim_emergency_stop = False
        _sim_running = False
    print("🕯️ [sim] emergency stop cleared!", fg="#ffaa00")

def emergency_event(p:HWGPIO):
    if p.state:  sim_emergency_stop()
    else:  sim_emergency_reset()
HWGPIO_MONITOR.add_listener(emergency, emergency_event)


@sim_operation(delay=0.5)  # adjust delay per step if needed
def roller_move(**kwargs):
    """
    Cycle some rollers using sim_operation decorator.
    """
    steps = {
        0: lambda: rm.set_value_list([1, 0, 0]),
        1: lambda: rm.set_value_list([0, 1, 0]),
        2: lambda: rm.set_value_list([0, 0, 1]),
        3: lambda: rm.set_value_list([0, 0, 0]),
        4: lambda: rm.set_value_list([1, 1, 1]),
        5: lambda: rm.set_value_list([2, 2, 2]),
        6: lambda: rm.set_value_list([2, 2, 0]),
        7: lambda: rm.set_value_list([2, 0, 0]),
        8: lambda: rm.set_value_list([0, 0, 0]),
    }
    return execute_steps(steps, **kwargs)

@sim_operation(delay=0.5)
def user_loading_meter(**kwargs):
    """ pretend that a user put meter on belt """
    value = mdm.get_value()
    if not mdm.is_ch_empty(0, value):
        print("🕯️ [sim] not empty to pretend load", fg="#ffaa00")
        return
    steps = {
        0: lambda: mdm.set_value(mdm.get_value() | 0b1),
        1: lambda: mdm.set_value(mdm.get_value() | 0b11),
    }
    return execute_steps(steps, **kwargs)

@sim_operation(delay=0.5)
def user_unloading_meter(**kwargs):
    """ user unloaded meter from 3rd station """
    value = mdm.get_value()
    if mdm.is_ch_empty(2, value):
        print("🕯️ [sim] nothing to unload")
        return
    steps = {
        0: lambda: mdm.set_ch_bit(2,0,False),
        1: lambda: mdm.set_ch_bit(2,1,False),
        2: lambda: mdm.set_ch_bit(2,2,False),
    }
    return execute_steps(steps, **kwargs)

def meter_random(**kwargs):
    n1 = random.choice([0, 7])
    n2 = random.choice([0, 7])
    n3 = random.choice([0, 7])

    curr = packer(states.get("mds", 0))
    n = (n3 << 6) | (n2 << 3) | n1

    if curr == n:
        return meter_random()
    mdm.set_value(n)


def toggle_emergency(**kwargs):
    emergency.state = not bool(emergency.state)



testimgsrc = "running-cat.gif"
testdataurl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAABGdBTUEAALGPC/xhBQAAAAlwSFlzAAAOwQAADsEBuJFr7QAAABl0RVh0U29mdHdhcmUAcGFpbnQubmV0IDQuMC4yMfEgaZUAAAAfSURBVDhPY/j+v49sNKqZRDSqmUQ0qplENPI0/+8DAOnW7m6FxOUUAAAAAElFTkSuQmCC"

""" 
# so example for cv2 ... but could be np array or w/e
img = cv2.imread("image.png")
src = "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", img)[1]).decode()
"""


def on_question(**kwargs):
    def gimme_boolean():
        ask_clients(
            title="Are you handsome?",
            msg="very handsome?",
            qtype="boolean",
            confirm="mucho",
            cancel="poco",
            src=testdataurl,
        )

    def gimme_boolean():
        ask_clients(
            title="Question for you sir",
            msg="very handsome?",
            qtype="boolean",
            confirm="mucho",
            cancel="poco",
            src="https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Fi.pinimg.com%2Foriginals%2Fb6%2Fa6%2Fd5%2Fb6a6d50de7eb36065b98ebd254d46cd5.jpg&f=1&nofb=1&ipt=e4c991dc508ad98700c83b94b65129a61621b817e5711b3fffe9a4f625d236f6",
        )

    def gimme_number():
        ask_clients(
            title="Age",
            msg="How old are you foo",
            qtype="number",
            confirm="confirm",
            src=testimgsrc,
        )

    def gimme_string():
        ask_clients(
            title="Name", msg="name?", qtype="string", confirm="confirm", src=testimgsrc
        )

    option = kwargs.get("type", 0)

    if option == 1:
        gimme_number()
    elif option == 2:
        gimme_string()
    else:
        gimme_boolean()


def on_meter(**kwargs):
    option = kwargs.get("type", 0)
    res = None
    if option == 0:
        res = meter_random()
    elif option == 1:
        bay = kwargs.get("bay", -1)
        if bay>=0 and bay<3:
            v = 0 if mdm.get_ch_value(bay) else 0b111
            mdm.set_ch_value(bay, v)
    elif option == 2:
        mdm.set_value(0)
    elif option == 3: 
        mdm.set_ch_bit(0,0,1)
    elif option == 10:
        res = user_loading_meter()
    elif option == 14:
        res = user_unloading_meter()

    return res if res is not None else ("", 200)


def on_action(action, **kwargs):
    res = None
    if not secrets.MOCK: print("🕯️ [sim] not mock so not safe to sim", fg="#ffaa00")
    elif action == "roller":
        res = roller_move(**kwargs)
    elif action == "meter":
        res = on_meter(**kwargs)
    elif action == "question":
        res = on_question(**kwargs)
    elif action == "emergency":
        res = toggle_emergency(**kwargs)
    
    return res if res is not None else ("", 200)

@sim_operation(delay=0.5)
def mock_station_load(**kwargs):
    option = kwargs.get("type", 0)
    boxes = sensors_to_boxes(mdm.get_value_list())
    frames = _mock_station_load_frames(option, boxes, **kwargs)

    if not frames:
        print(f"🕯️ [sim] station load {option!r} blocked/no-op", fg="#ffaa00")
        return

    motor_values = _mock_station_load_motors(option)
    def render_frame(frame: list[int], *, stop_motors: bool = False):
        mdm.set_value_list(boxes_to_sensors(frame))
        if stop_motors:
            rm.set_value_list([rm.COAST, rm.COAST, rm.COAST])
        if stop_motors and option == "L" and (meter_ip := kwargs.get("meter_ip")):
            station.set_meter_bay_guess(meter_ip)

    steps = {
        0: lambda: rm.set_value_list(motor_values),
        **{
            index: (
                lambda frame=frame, is_last=index == len(frames):
                    render_frame(frame, stop_motors=is_last)
            )
            for index, frame in enumerate(frames, start=1)
        },
    }
    return execute_steps(steps, **kwargs)


def _find_box_for_range(boxes: list[int], lower: int, upper: int, *, prefer_right: bool) -> int | None:
    candidates = [
        index for index, box_left in enumerate(boxes)
        if lower <= box_left <= upper
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda index: boxes[index]) if prefer_right else min(candidates, key=lambda index: boxes[index])


def _single_move_frames(boxes: list[int], lower: int, upper: int, target: int, *, prefer_right: bool) -> list[list[int]]:
    box_index = _find_box_for_range(boxes, lower, upper, prefer_right=prefer_right)
    if box_index is None:
        return []
    if boxes[box_index] == target:
        return []
    if not move_is_clear(boxes, box_index, target):
        return []
    return move_box_frames(boxes, box_index, target)


def _shift_all_frames(boxes: list[int]) -> list[list[int]]:
    moves: dict[int, int] = {}

    middle_index = next((index for index, box_left in enumerate(boxes) if box_left == BAY_STARTS[1]), None)
    if middle_index is not None and move_is_clear(boxes, middle_index, BAY_STARTS[2]):
        moves[middle_index] = BAY_STARTS[2]

    left_index = next((index for index, box_left in enumerate(boxes) if box_left == BAY_STARTS[0]), None)
    if left_index is not None:
        candidate_moves = {**moves, left_index: BAY_STARTS[1]}
        candidate_boxes = boxes[:]
        for index, target in candidate_moves.items():
            candidate_boxes[index] = target
        if boxes_are_valid(candidate_boxes):
            moves[left_index] = BAY_STARTS[1]

    if not moves:
        return []
    return move_many_frames(boxes, moves)


def _coerce_unload_steps(**kwargs) -> int:
    try:
        return max(0, min(2, int(kwargs.get("steps", 0))))
    except (TypeError, ValueError):
        return 0


def _mock_station_load_frames(option: str, boxes: list[int], **kwargs) -> list[list[int]]:
    if option == 'L':
        return _single_move_frames(boxes, -2, 0, BAY_STARTS[0], prefer_right=False)
    if option == 'M':
        return _single_move_frames(boxes, BAY_STARTS[0], BAY_STARTS[1] - 1, BAY_STARTS[1], prefer_right=True)
    if option == 'R':
        return _single_move_frames(boxes, BAY_STARTS[1], BAY_STARTS[2] - 1, BAY_STARTS[2], prefer_right=True)
    if option == 'RU':
        target = BAY_STARTS[2] + _coerce_unload_steps(**kwargs)
        return _single_move_frames(boxes, BAY_STARTS[2], target, target, prefer_right=True)
    if option == 'ML':
        return _single_move_frames(boxes, BAY_STARTS[0], BAY_STARTS[1], BAY_STARTS[0], prefer_right=False)
    if option == 'RM':
        return _single_move_frames(boxes, BAY_STARTS[1], BAY_STARTS[2], BAY_STARTS[1], prefer_right=False)
    if option == 'ALL':
        return _shift_all_frames(boxes)
    return []


def _mock_station_load_motors(option: str) -> list[int]:
    if option == 'L':
        return [rm.FORWARD, rm.COAST, rm.COAST]
    if option == 'M':
        return [rm.FORWARD, rm.FORWARD, rm.COAST]
    if option == 'R':
        return [rm.COAST, rm.FORWARD, rm.FORWARD]
    if option == 'RU':
        return [rm.COAST, rm.COAST, rm.FORWARD]
    if option == 'ALL':
        return [rm.FORWARD, rm.FORWARD, rm.FORWARD]
    if option == 'ML':
        return [rm.REVERSE, rm.REVERSE, rm.COAST]
    if option == 'RM':
        return [rm.COAST, rm.REVERSE, rm.REVERSE]
    return [rm.COAST, rm.COAST, rm.COAST]
    
def on_mock(handler, action, **kwargs):
    res = None
    if handler == station:
        if action == 'load': 
            res = mock_station_load(**kwargs)
        else:
            res = station.on_action(action, **kwargs)
    elif handler == override:
        res = override.on_action(action, **kwargs)

    elif handler == program:
        res = program.on_action(action, **kwargs)

    return res if res is not None else ("", 200)
    

__all__ = ['on_action']

if __name__ == "__main__":
    meter_random()
