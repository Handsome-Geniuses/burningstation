
# ====================================================
# controls turning on/off motors to move meters
# ====================================================
from lib.gpio import *
from lib.sse.sse_queue_manager import SSEQM
from lib.system import states
import time
from asyncdec import AsyncManager, async_fire_and_forget
am_station = AsyncManager("am_station")

def emergency_event(p:HWGPIO):
    if p.state: am_station.emergency_stop()
    else: am_station.emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,emergency_event)


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
    pass
# ----------------------------------------------------
# Align meter in loading bay
# ----------------------------------------------------
def load_L_precheck(**kwargs):
    value = mdm.get_value()
    if mdm.is_ch_full(0, value):
        return "Already loaded", 204
    elif not mdm.get_ch_bit(0, 0, value):
        return "Nothing to load", 409
    return None     # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_L_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout)
def load_L(**kwargs):
    """Meter was loaded onto station1. Needs alignment"""
    rm.set_value_list([rm.FORWARD, rm.COAST, rm.COAST])
    while not states['mds'][2]:
        time.sleep(0.1)
    print("[load_L] Load completed")
    return "[load_L] Load completed", 200

# ----------------------------------------------------
# Move meter into middle
# ----------------------------------------------------
def load_M_precheck(**kwargs):
    value = mdm.get_value()
    if not mdm.is_ch_full(0, value):
        return "L not loaded", 204
    if not mdm.is_ch_empty(1, value):
        return "M is occupied", 409
    return None     # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_M_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout)
def load_M(**kwargs):
    """Moves meter from station1 to station2"""
    rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.COAST])
    while not states['mds'][5]: time.sleep(0.1)
    return "[load_M] Load completed", 200

# ----------------------------------------------------
# Move meter into unloading station
# ----------------------------------------------------
def load_R_precheck(**kwargs):
    value = mdm.get_value()
    if mdm.is_ch_full(2, value): return None
    if not mdm.is_ch_full(1, value):
        return "M not loaded", 204
    elif not mdm.is_ch_empty(2, value):
        return "R is occupied", 409
    return None     # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_R_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout)
def load_R(**kwargs):
    """Moves meter from station2 to station3"""
    rm.set_value_list([rm.COAST, rm.FORWARD, rm.FORWARD])
    while not states["mds"][8]: time.sleep(0.1)
    rm.set_value_list([rm.COAST, rm.COAST, rm.FORWARD])
    while states["mds"][6]: time.sleep(0.1)
    print("[load_R] Load completed")
    return "[load_R] Load completed", 200

# ----------------------------------------------------
# Move middle to unloading and load new middle
# ----------------------------------------------------
def load_ALL_precheck(**kwargs):
    value = mdm.get_value()
    if not mdm.is_ch_full(0,value): 
        return "[load_ALL] L->M nothing to move", 204
    elif not mdm.is_ch_full(1,value): 
        return "[load_ALL] M->R nothing to move", 204
    elif not mdm.is_ch_empty(2,value): 
        return "[load_ALL] R occupied", 204
    return None     # passed pre-check

@am_station.operation(timeout=3.0, precheck=load_ALL_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout)
def load_ALL(**kwargs):
    value = mdm.get_value()
    rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.FORWARD])
    while states['mds'][5]:
        time.sleep(0.1)
    while not states['mds'][5]:
        time.sleep(0.1)
    rm.set_value_list([rm.COAST, rm.COAST, rm.FORWARD])
    while states['mds'][6]:
        time.sleep(0.1)
    print("[load_ALL] Load completed")
    return "[load_ALL] Load completed", 200



# ----------------------------------------------------
# SECRET! HANDSOME PEOPLE ONLY
# ---------------------------------------------------- 
def load_M_to_L_precheck(**kwargs):
    value = mdm.get_value()
    if not mdm.is_ch_full(1, value):
        return "M not loaded", 204
    elif not mdm.is_ch_empty(0, value):
        return "L is occupied", 409
    return None  # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_M_to_L_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout)
def load_M_to_L(**kwargs):
    """Moves meter from middle station (M) back to left station (L)"""
    rm.set_value_list([rm.REVERSE, rm.REVERSE, rm.COAST])
    while not states['mds'][0]: 
        time.sleep(0.1)
    print("[load_M_to_L] completed")
    return "[load_M_to_L] completed", 200

def load_R_to_M_precheck(**kwargs):
    value = mdm.get_value()
    if mdm.get_ch_value(2, value) not in (0b110, 0b111):
        return "R not loaded", 204
    elif not mdm.is_ch_empty(1, value):
        return "M is occupied", 409
    return None  # passed pre-check

@am_station.operation(timeout=20.0, precheck=load_R_to_M_precheck, on_start=on_load_start, on_done=on_load_done, on_timeout=on_load_timeout)
def load_R_to_M(**kwargs):
    """Moves meter from right station (R) back to middle station (M)"""
    rm.set_value_list([rm.COAST, rm.REVERSE, rm.REVERSE])
    while not states['mds'][3]: 
        time.sleep(0.1)
    print("[load_R_to_M] completed")
    return "[load_R_to_M] completed", 200


# ----------------------------------------------------
# handle moving meter around
# ----------------------------------------------------   
def on_load(**kwargs):
    option = kwargs.get('type', None)
    if option==None: return
    elif option=='L': return load_L()
    elif option=='M': return load_M()
    elif option=='R': return load_R()
    elif option=='ALL': return load_ALL() 
    elif option=='ML': return load_M_to_L()
    elif option=='RM': return load_R_to_M()


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

    elif option=='L1': lm.lamp(0, state=not states['lamp'][0], dc=dc)
    elif option=='L2': lm.lamp(1, state=not states['lamp'][1], dc=dc)
    # elif option=='L1DC' and dc!=-1: lm.lamp1_dc(dc)
    # elif option=='L2DC' and dc!=-1: lm.lamp2_dc(dc)

# ----------------------------------------------------
# determine action and go!
# ----------------------------------------------------
def on_action(action, **kwargs):
    res = None
    # if secrets.MOCK: print("[station] is mock so skipping")
    if False: pass
    elif action=="load":  return on_load(**kwargs)
    elif action=="tower": return on_tower(**kwargs)
    elif action=="lamp":  return on_lamp(**kwargs)

    return res if res is not None else ("", 200)

if __name__ == "__main__":
    try:
        input("")
    finally:
        rm.set_value_list([0,0,0])