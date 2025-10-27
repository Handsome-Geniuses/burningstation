import random
import threading

from lib.gpio import *
from lib.sse import ask_clients
import lib.system.station as station
from lib.system.states import states
from lib.utils import packer, secrets

_sim_lock = threading.Lock()
_sim_running = False
_sim_emergency_stop = False


def sim_operation(delay: float = 1.0):
    """Decorator that manages threading, _sim_lock, and _sim_running for simulation operations"""

    def decorator(fn):
        def wrapper(**kwargs):
            global _sim_running
            global _sim_lock
            global _sim_emergency_stop
            
            with _sim_lock:
                if _sim_emergency_stop:
                    print("sim emergency stop active!")
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

def execute_steps(steps: dict, **kwargs):
    """Execute a dictionary of steps with delays between them"""
    global _sim_emergency_stop
    delay = kwargs.get('delay', 1.0)
    
    def run_step(i=0):
        if _sim_emergency_stop:
            return
        if i in steps:
            steps[i]()
        if i < max(steps.keys()) and not _sim_emergency_stop:
            threading.Timer(delay, lambda i=i: run_step(i + 1)).start()

    run_step(0)
    return "", 200

def sim_emergency_stop():
    """Activate emergency stop - prevents new sim operations from starting"""
    global _sim_emergency_stop
    with _sim_lock:
        _sim_emergency_stop = True
    print("Sim emergency stop activated!")

def sim_emergency_reset():
    """Reset emergency stop flag - call this to allow sim operations again"""
    global _sim_emergency_stop
    with _sim_lock:
        _sim_emergency_stop = False
    print("Sim emergency stop cleared!")

def emergency_event(p:HWGPIO):
    if p.state:  sim_emergency_stop()
    else:  sim_emergency_reset()
HWGPIO_MONITOR.add_listener(emergency, emergency_event)


@sim_operation(delay=1.0)  # adjust delay per step if needed
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
        print("[person_loading_meter] not empty to pretend load")
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
        print("[user_unloading_meter] nothing to unload")
        return
    steps = {
        0: lambda: mdm.set_ch_bit(2,0,False),
        1: lambda: mdm.set_ch_bit(2,1,False),
        2: lambda: mdm.set_ch_bit(2,2,False),
    }
    return execute_steps(steps, **kwargs)


@sim_operation(delay=1.0)
def user_press_load_L(**kwargs):
    """ this just pretends the meter is actually moving """
    msg, code = station.load_L()
    if code==200:
        steps = {
            0: lambda: mdm.set_ch_bit(0,1,True),
            1: lambda: mdm.set_ch_bit(0,2,True),
        }
        return execute_steps(steps, **kwargs)


@sim_operation(delay=1.0)
def user_press_load_M(**kwargs):
    """ this just pretends the meter is actually moving """
    msg, code = station.load_M()
    if code==200:
        steps = {
            1: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 0),
            2: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 1),
            3: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 2),
        }
        return execute_steps(steps, **kwargs)


@sim_operation(delay=1.0)
def user_press_load_R(**kwargs):
    """ this just pretends the meter is actually moving """
    msg, code = station.load_R()
    if code==200:
        steps = {
            0: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 3),
            1: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 4),
            2: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 5),
            3: lambda: mdm.set_ch_bit(2,0,False),
        }
        return execute_steps(steps, **kwargs)

@sim_operation(delay=1.0)
def user_press_shift_all(**kwargs):
    """Simulate user pressing shift all -> chains M->R and L->M"""

    def on_R_done():
        # Load M
        if station.load_M()[1] == 200:
            steps_M = {
                1: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 0),
                2: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 1),
                3: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 2),
            }
            execute_steps(steps_M, **kwargs)

    # Load R
    if station.load_R(on_done=on_R_done)[1] == 200:
        steps_R = {
            0: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 3),
            1: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 4),
            2: lambda: mdm.set_value(mdm.get_value() ^ 0b1001 << 5),
            3: lambda: mdm.set_ch_bit(2, 0, False),
        }
        execute_steps(steps_R, **kwargs)
    
    

def meter_random(**kwargs):
    n1 = random.choice([0, 7])
    n2 = random.choice([0, 7])
    n3 = random.choice([0, 7])

    curr = packer(states.get("mds", 0))
    n = (n3 << 6) | (n2 << 3) | n1

    if curr == n:
        return meter_random()
    mdm.set_value(n)


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


def toggle_emergency(**kwargs):
    emergency.state = not emergency.state


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
    elif option == 10:
        res = user_loading_meter()
    elif option == 11:
        res = user_press_load_L()
    elif option == 12:
        res = user_press_load_M()
    elif option == 13:
        res = user_press_load_R()
    elif option == 14:
        res = user_unloading_meter()
    elif option == 15:
        res = user_press_shift_all()

    return res if res is not None else ("", 200)


def on_action(action, **kwargs):
    res = None
    if not secrets.MOCK: print("[sim] not mock so not safe to sim")
    elif action == "roller":
        res = roller_move(**kwargs)
    elif action == "meter":
        res = on_meter(**kwargs)
    elif action == "question":
        res = on_question(**kwargs)
    elif action == "emergency":
        res = toggle_emergency(**kwargs)
    
    return res if res is not None else ("", 200)

__all__ = ['on_action']

if __name__ == "__main__":
    meter_random()