import random
import threading
import time

from lib.gpio import *
from lib.sse import ask_clients
from lib.system import last_roller_states,last_emergency_state, mds

_roller_lock = threading.Lock()
_roller_running = False

def roller_move(**kwargs):
    """
    cycle some rollers
    """
    global _roller_running
    with _roller_lock:
        if _roller_running:
            return "Already running", 409
        _roller_running = True

    steps = [
        [True, False, False],
        [True, True, False],
        [True, True, True],
        [False, False, False],
    ]

    def run_step(i=0):
        if i >= len(steps):
            global _roller_running
            with _roller_lock:
                _roller_running = False
            return

        for j in range(3):
            rollers[j].state = steps[i][j]

        threading.Timer(1.2, lambda: run_step(i + 1)).start()

    run_step(0)
    return "", 200


def meter_random(**kwargs):
    """
    write random value to pcfios and trigger interrupt for listener
    """
    if PCF8574.MOCK:
        curr = pcfio1.read_byte()
        byte = random.randint(0, 0xFF)
        pcfio1.write_byte(byte)
        pcfio1_changed = curr != byte

        curr = pcfio2.get_state(0)
        bit = random.choice([True, False])
        pcfio2_byte_ = pcfio2.set_state(0, bit)
        pcfio2_changed = curr != bit
        
        print(pcfio2_changed)

        if pcfio1_changed:
            pcfio1_int.state = 1
            time.sleep(0.01)
            pcfio1_int.state = 0

        if pcfio2_changed:
            pcfio2_int.state = 1
            time.sleep(0.01)
            pcfio2_int.state = 0


def toggle_emergency(**kwargs):
    emergency.state = not emergency.state


testimgsrc = "running-cat.gif"
testdataurl = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAABGdBTUEAALGPC/xhBQAAAAlwSFlzAAAOwQAADsEBuJFr7QAAABl0RVh0U29mdHdhcmUAcGFpbnQubmV0IDQuMC4yMfEgaZUAAAAfSURBVDhPY/j+v49sNKqZRDSqmUQ0qplENPI0/+8DAOnW7m6FxOUUAAAAAElFTkSuQmCC"

""" 
# so example for cv2 ... but could be np array or w/e
img = cv2.imread("image.png")
src = "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", img)[1]).decode()
"""


def question(**kwargs):
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







def start(**kwargs):
    if mds.is_ch_full(1):
        """ middle is occupied so runnable """

    # else 












def on_action(action, **kwargs):
    res = None
    if action == "roller":
        res = roller_move(**kwargs)
    elif action == "meter":
        res = meter_random(**kwargs)
    elif action == "question":
        res = question(**kwargs)
    elif action == "emergency":
        res = toggle_emergency(**kwargs)
    return res if res is not None else ("", 200)


