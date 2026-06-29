
# ====================================================
# controls turning on/off motors to move meters
# ====================================================
from lib.gpio import *
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.system import states
import time
from prettyprint import STYLE, prettyprint as print
from asyncdec import AsyncManager, async_fire_and_forget
from lib.robot.robot_client import RobotClient
from lib.system.bay_guess import BAY_GUESS_BAY_STARTS, empty_bay_guess, place_meter
from lib.system.belt_logic import BAY_STARTS, BOX_LEFT_MAX, boxes_are_valid, sensors_to_boxes

from lib.store import store

am_station = AsyncManager("am_station")

def emergency_event(p:HWGPIO):
    if p.state: am_station.emergency_stop()
    else: am_station.emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,emergency_event)

def check_robot_clear_of_conveyor():
    robot = RobotClient()

    resp = robot.send_command("is_in_conveyor_path")
    busy = resp.get("busy", False)
    in_bbox = resp.get("in_conveyor_bbox", False)

    if not busy and not in_bbox:
        return

    try:
        if busy:
            robot.send_command("abort_program")
            robot.wait_until_ready(wait_timeout=10)

        job_id = robot.run_program("run_safe_home")
        robot.wait_for_event("program_done", job_id=job_id, timeout=10)
    except Exception as e:
        raise RuntimeError(f"Robot failed to clear conveyor zone: {e}")


def _find_box_for_range(boxes: list[int], lower: int, upper: int, *, prefer_right: bool) -> int | None:
    candidates = [
        index for index, box_left in enumerate(boxes)
        if lower <= box_left <= upper
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda index: boxes[index]) if prefer_right else min(candidates, key=lambda index: boxes[index])


def _move_is_clear(boxes: list[int], box_index: int, target: int) -> bool:
    next_boxes = boxes[:]
    next_boxes[box_index] = target
    return boxes_are_valid(next_boxes)


def _has_boxes_at(targets: list[int]) -> bool:
    boxes = sensors_to_boxes(mdm.get_value_list())
    return all(target in boxes for target in targets)

def _broadcast_bay_guess():
    SSEQM.broadcast("state", key_payload("bayGuess", states["bayGuess"]))

def set_meter_bay_guess(meter_ip: str, bay_index: int = 0):
    states["bayGuess"] = place_meter(
        states.get("bayGuess", empty_bay_guess()),
        meter_ip,
        BAY_GUESS_BAY_STARTS[bay_index],
    )
    _broadcast_bay_guess()

@async_fire_and_forget
def on_load_start():
    tm.set_value_list([0,1,0,0])
    tm.buzz(1)
    time.sleep(1)
    tm.buzz(0)

@async_fire_and_forget
def on_load_done(stopped):
    rm.set_value(0)
    tm.yellow(0)
    if not stopped:
        tm.green(1)
        for i in range(2):
            tm.buzz(1)
            time.sleep(0.05)
            tm.buzz(0)
            time.sleep(0.1)
    else:
        tm.red(True)
        SSEQM.broadcast('notify', {'ntype': 'error','msg': 'meter move error/timeout'})
        for i in range(3):
            tm.buzz(1)
            time.sleep(1)
            tm.buzz(0)
            time.sleep(1)

@async_fire_and_forget
def on_load_timeout():
    emergency.state = True

@async_fire_and_forget
def on_load_exception(e: Exception):
    print(f"❌[Station] load error: {e}", fg="#ff5555", style=STYLE.BOLD)
    emergency.state = True
# ----------------------------------------------------
# Align meter in loading bay
# ----------------------------------------------------
def load_L_precheck(**kwargs):
    boxes = sensors_to_boxes(mdm.get_value_list())
    if BAY_STARTS[0] in boxes:
        return "Already loaded", 204
    elif not any(box <= BAY_STARTS[0] for box in boxes):
        return "Nothing to load", 409
    return None     # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_L_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_L(**kwargs):
    """Meter was loaded onto station1. Needs alignment"""
    rm.set_value_list([rm.FORWARD, rm.COAST, rm.COAST])
    while BAY_STARTS[0] not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    if meter_ip := kwargs.get("meter_ip"):
        set_meter_bay_guess(meter_ip)
    print("✅[Station] load_L completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_L] Load completed", 200

# ----------------------------------------------------
# Move meter into middle
# ----------------------------------------------------
def load_M_precheck(**kwargs):
    boxes = sensors_to_boxes(mdm.get_value_list())
    box_index = _find_box_for_range(boxes, BAY_STARTS[0], BAY_STARTS[1] - 1, prefer_right=True)
    if box_index is None:
        return "L not loaded", 204
    if not _move_is_clear(boxes, box_index, BAY_STARTS[1]):
        return "M is occupied", 409
    return None     # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_M_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_M(**kwargs):
    """Moves meter from station1 to station2"""
    rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.COAST])
    while BAY_STARTS[1] not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    return "[load_M] Load completed", 200

# ----------------------------------------------------
# Move meter into unloading station
# ----------------------------------------------------
def load_R_precheck(**kwargs):
    boxes = sensors_to_boxes(mdm.get_value_list())
    box_index = _find_box_for_range(boxes, BAY_STARTS[1], BAY_STARTS[2] - 1, prefer_right=True)
    if box_index is None:
        return "M not loaded", 204
    elif not _move_is_clear(boxes, box_index, BAY_STARTS[2]):
        return "R is occupied", 409
    return None     # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_R_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_R(**kwargs):
    """Moves meter from station2 to station3"""
    rm.set_value_list([rm.COAST, rm.FORWARD, rm.FORWARD])
    while BAY_STARTS[2] not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    print("✅[Station] load_R completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_R] Load completed", 200

def _coerce_unload_steps(**kwargs) -> int:
    try:
        return int(kwargs.get("steps", 0))
    except (TypeError, ValueError):
        return 0

def load_R_unload_precheck(**kwargs):
    steps = _coerce_unload_steps(**kwargs)
    target = BAY_STARTS[2] + steps
    if steps <= 0:
        return None
    if target > BOX_LEFT_MAX:
        return "Unload target out of range", 409

    boxes = sensors_to_boxes(mdm.get_value_list())
    box_index = _find_box_for_range(boxes, BAY_STARTS[2], target, prefer_right=True)
    if box_index is None:
        return "R not loaded", 204
    elif not _move_is_clear(boxes, box_index, target):
        return "Unload position occupied", 409
    return None

@am_station.operation(timeout=20.0, precheck=load_R_unload_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_R_unload(**kwargs):
    """Moves the right station meter farther into the unload area."""
    steps = _coerce_unload_steps(**kwargs)
    target = BAY_STARTS[2] + steps
    rm.set_value_list([rm.COAST, rm.COAST, rm.FORWARD])
    while target not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    print("✅[Station] load_R_unload completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_R_unload] completed", 200

# ----------------------------------------------------
# Move middle to unloading and load new middle
# ----------------------------------------------------
def load_ALL_precheck(**kwargs):
    boxes = sensors_to_boxes(mdm.get_value_list())
    if BAY_STARTS[0] not in boxes:
        return "[load_ALL] L->M nothing to move", 204
    elif BAY_STARTS[1] not in boxes:
        return "[load_ALL] M->R nothing to move", 204
    elif any(box >= BAY_STARTS[2] for box in boxes):
        return "[load_ALL] R occupied", 204
    elif not boxes_are_valid([BAY_STARTS[1], BAY_STARTS[2]]):
        return "[load_ALL] invalid move", 204
    return None     # passed pre-check

@am_station.operation(timeout=3.0, precheck=load_ALL_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_ALL(**kwargs):
    rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.FORWARD])
    while not _has_boxes_at([BAY_STARTS[1], BAY_STARTS[2]]):
        time.sleep(0.1)
    print("✅[Station] load_ALL completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_ALL] Load completed", 200



# ----------------------------------------------------
# SECRET! HANDSOME PEOPLE ONLY
# ---------------------------------------------------- 
def load_M_to_L_precheck(**kwargs):
    boxes = sensors_to_boxes(mdm.get_value_list())
    box_index = _find_box_for_range(boxes, BAY_STARTS[0], BAY_STARTS[1], prefer_right=False)
    if box_index is None:
        return "M not loaded", 204
    elif not _move_is_clear(boxes, box_index, BAY_STARTS[0]):
        return "L is occupied", 409
    return None  # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_M_to_L_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_M_to_L(**kwargs):
    """Moves meter from middle station (M) back to left station (L)"""
    rm.set_value_list([rm.REVERSE, rm.REVERSE, rm.COAST])
    while BAY_STARTS[0] not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    print("✅[Station] load_M_to_L completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_M_to_L] completed", 200

def load_R_to_M_precheck(**kwargs):
    boxes = sensors_to_boxes(mdm.get_value_list())
    box_index = _find_box_for_range(boxes, BAY_STARTS[1], BAY_STARTS[2], prefer_right=False)
    if box_index is None:
        return "R not loaded", 204
    elif not _move_is_clear(boxes, box_index, BAY_STARTS[1]):
        return "M is occupied", 409
    return None  # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_R_to_M_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_R_to_M(**kwargs):
    """Moves meter from right station (R) back to middle station (M)"""
    rm.set_value_list([rm.COAST, rm.REVERSE, rm.REVERSE])
    while BAY_STARTS[1] not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    print("✅[Station] load_R_to_M completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_R_to_M] completed", 200


# going to reuse the R to M precheck
@am_station.operation(timeout=20.0, precheck=load_R_to_M_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout, on_exception=on_load_exception)
def load_R_to_L(**kwargs):
    """Moves meter from right station (R) back to LEFT station (L)"""
    rm.set_value_list([rm.REVERSE, rm.REVERSE, rm.REVERSE])
    while BAY_STARTS[0] not in sensors_to_boxes(mdm.get_value_list()):
        time.sleep(0.1)
    print("✅[Station] load_R_to_L completed.", fg="#00ff00", style=STYLE.BOLD)
    return "[load_R_to_L] completed", 200

# ----------------------------------------------------
# handle moving meter around
# ----------------------------------------------------   
def on_load(**kwargs):
    option = kwargs.get('type', None)
    
    if option in ("M", "R", "RU", "ALL", "ML", "RM", "RL"):
        check_robot_clear_of_conveyor()
    
    if option==None: return
    elif option=='L': return load_L(**kwargs)
    elif option=='M': return load_M()
    elif option=='R': return load_R()
    elif option=='RU': return load_R_unload(**kwargs)
    elif option=='ALL': return load_ALL() 
    elif option=='ML': return load_M_to_L()
    elif option=='RM': return load_R_to_M()
    elif option=='RL': return load_R_to_L() # dont actually use this.33


# ----------------------------------------------------
# tower control red, yellow, green, buzzer
# ----------------------------------------------------
def on_tower(**kwargs):
    option = kwargs.get('type', None)
    if option==None: return
    elif option=='R': tm.red( not states['tower'][0])
    elif option=='Y': tm.yellow( not states['tower'][1])
    elif option=='G': tm.green( not states['tower'][2])
    elif option=='BUZ': tm.buzz( not states['tower'][3])

    elif option=='+R': tm.red(True)
    elif option=='-R': tm.red(False)
    elif option=='+Y': tm.yellow(True)
    elif option=='-Y': tm.yellow(False)
    elif option=='+G': tm.green(True)
    elif option=='-G': tm.green(False)

# ----------------------------------------------------
# solar lamp control
# ----------------------------------------------------
def on_lamp(**kwargs):
    option = kwargs.get('type', None)
    dc = kwargs.get('dc', None)
    state = kwargs.get('state', None)
    if option==None: return
    # elif option=='L1': lm.lamp1(not states['lamp'][0])
    # elif option=='L2': lm.lamp2(not states['lamp'][1])
    # elif option=='+L1': lm.lamp1(True)
    # elif option=='-L1': lm.lamp1(False)
    # elif option=='+L2': lm.lamp2(True)
    # elif option=='-L2': lm.lamp2(False)



    # elif option=='L1': lm.lamp1_enable(not states['lamp'][0])
    # elif option=='L2': lm.lamp2_enable(not states['lamp'][1])
    # elif option=='L1DC' and dc!=-1: lm.lamp1_dc(dc)
    # elif option=='L2DC' and dc!=-1: lm.lamp2_dc(dc)

    elif option=='L1': lm.lamp(0, state=state, dc=dc)
    elif option=='L2': lm.lamp(1, state=state, dc=dc)
    # elif option=='L1DC' and dc!=-1: lm.lamp1_dc(dc)
    # elif option=='L2DC' and dc!=-1: lm.lamp2_dc(dc)


def on_mode(**kwargs):
    mode = kwargs.get('value', None)
    if mode == None:                                # default manual
        states['mode']='manual'
    elif states['mode'] == mode:                    # do nothing if no change
        return
    elif mode == 'manual': 
        states['mode']='manual'                    # manual mode
    elif mode == 'auto':                            # auto mode but check if allowed
        if store.settings.handsome.allow_auto_switch:
            states['mode']='auto'
        elif all(not b for b in mdm.get_value_list()[2:]):
            states['mode']='auto'
        else: 
            SSEQM.broadcast("notify", {"ntype": "warn", "msg": "remove meters first"})
            return

    # if mode==None: states['mode'] = 'auto' if states['mode']=='manual' else 'manual'
    # elif mode not in ('auto','manual'): return
    # else: states['mode'] = mode
    SSEQM.broadcast("state", key_payload("mode", states['mode']))

def on_emergency(**kwargs):
    value = kwargs.get('value', None)
    if value is None:
        return "Missing emergency value", 400
    emergency.state = bool(value)
    return "", 200



# idk what the program name is for shut down?
def on_robot(**kwargs):
    action = kwargs.get('wdyw', None)
    print(kwargs)
    print("hello?")
    if action == None: return 
    elif action == "home": 
        robot = RobotClient()
        job_id = robot.run_program("run_safe_home")
        robot.wait_for_event("program_done", job_id=job_id, timeout=10)
    elif action == "off" : 
        robot = RobotClient()
        job_id = robot.run_program("run_safe_home")
        robot.wait_for_event("program_done", job_id=job_id, timeout=10)
        

# ----------------------------------------------------
# determine action and go!
# ----------------------------------------------------
def on_action(action, **kwargs):
    res = None
    # if secrets.MOCK: print("[station] is mock so skipping")
    if False: pass
    elif action=="load":  res = on_load(**kwargs)
    elif action=="tower": res = on_tower(**kwargs)
    elif action=="lamp":  res = on_lamp(**kwargs)
    elif action=="mode":  res = on_mode(**kwargs)
    elif action=="emergency": res = on_emergency(**kwargs)
    elif action=="robot": res = on_robot(**kwargs)

    return res if res is not None else ("", 200)

if __name__ == "__main__":
    try:
        input("")
    finally:
        rm.set_value_list([0,0,0])
