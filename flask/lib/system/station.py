
# ====================================================
# controls turning on/off motors to move meters
# ====================================================
# on function timeout, reset lock
from lib.gpio import *
from lib.system import states
import threading
from lib.utils import secrets
import time

_station_lock = threading.Lock()
_station_running = False
_station_emergency_stop = False

def station_operation(timeout: float = None):
    """Decorator for actual station operations with threading and optional callbacks"""

    def decorator(fn):
        def wrapper(**kwargs):
            global _station_running
            global _station_lock
            global _station_emergency_stop
            
            with _station_lock:
                if _station_emergency_stop:
                    print("station emergency stop active!")
                    return "Emergency stop active", 500
                if _station_running:
                    print("station busy!")
                    return "Already running", 409
                _station_running = True

            result = [("", 200)]
            
            on_done = kwargs.get('on_done', lambda: print(f"[{fn.__name__}] completed"))
            on_timeout = kwargs.get('on_timeout', lambda: print(f"[{fn.__name__}] timed out"))
            
            def run_operation():
                global _station_running
                global _station_lock
                try:
                    res = fn(**kwargs)
                    if res:
                        result[0] = res
                finally:
                    with _station_lock:
                        _station_running = False
                    
                    if on_done:
                        on_done()
            
            thread = threading.Thread(target=run_operation, daemon=True)
            thread.start()
            
            if timeout:
                def check_timeout():
                    thread.join(timeout=timeout)
                    if thread.is_alive():
                        print(f"Operation timed out after {timeout}s")
                        if on_timeout:
                            on_timeout()
                        with _station_lock:
                            _station_running = False
                
                threading.Thread(target=check_timeout, daemon=True).start()

            return result[0]

        return wrapper

    return decorator


def emergency_stop():
    """Activate emergency stop - prevents new operations from starting"""
    global _station_emergency_stop
    with _station_lock:
        _station_emergency_stop = True
    print("Station emergency stop activated!")


def emergency_reset():
    """Reset emergency stop flag - call this to allow operations again"""
    global _station_emergency_stop
    with _station_lock:
        _station_emergency_stop = False
    print("Station emergency stop cleared!")

def emergency_event(p:HWGPIO):
    if p.state: emergency_stop()
    else: emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,emergency_event)

@station_operation(timeout=10.0)
def load_L(**kwargs):
    """Meter was loaded onto station1. Needs alignment"""
    value = mdm.get_value()

    if mdm.is_ch_full(0, value):
        print("[load_L] already loaded")
        return "Already loaded", 204
    elif not mdm.get_ch_bit(0, 0, value):
        print("[load_L] nothing to load")
        return "Nothing to load", 409
    else: 
        rm.get_motor(0).forward()
        while not states['mds'][2]: time.sleep(0.1)
        rm.get_motor(0).coast()
        
    return "[load_L] Load completed", 200

@station_operation(timeout=10.0)
def load_M(**kwargs):
    """Moves meter from station1 to station2"""
    value = mdm.get_value()

    if not mdm.is_ch_full(0, value):
        print("[load_M] L not loaded yet")
        return "L not loaded", 204
    elif not mdm.is_ch_empty(1, value):
        print("[load_M] M is occupied")
        return "M is occupied", 409
    else:
        # rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.COAST])
        rm.get_motor(0).forward()
        rm.get_motor(1).forward()
        while not states['mds'][5]: time.sleep(0.1)
        # rm.set_value_list([rm.COAST, rm.COAST, rm.COAST])
        rm.get_motor(0).coast()
        rm.get_motor(1).coast()
        return "[load_M] Load completed", 200

@station_operation(timeout=10.0)
def load_R(**kwargs):
    """Moves meter from station2 to station3"""
    value = mdm.get_value()

    if not mdm.is_ch_full(1, value):
        print("[load_R] M not loaded yet")
        return "M not loaded", 204
    elif not mdm.is_ch_empty(2, value):
        print("[load_R] R is occupied")
        return "R is occupied", 409
    else:
        # rm.set_value_list([rm.COAST, rm.FORWARD, rm.FORWARD])
        rm.get_motor(1).forward()
        rm.get_motor(2).forward()
        while not states["mds"][8]: time.sleep(0.1)
        # rm.set_value_list([rm.COAST, rm.COAST, rm.FORWARD])
        rm.get_motor(1).coast()
        while states["mds"][6]: time.sleep(0.1)
        # rm.set_value_list([rm.COAST, rm.COAST, rm.COAST])
        rm.get_motor(2).coast()

        return "[load_R] Load completed", 200
    

@station_operation(timeout=20.0)
def load_RM(**kwargs):
    """SAFEST WAY BUT SLOW"""
    """Shift all meters through stations in sequence"""
    load_R(on_done=load_M)

@station_operation(timeout=20.0)
def load_ALL(**kwargs):
    value = mdm.get_value()

    if mdm.is_ch_full(0,value) and mdm.is_ch_full(1,value) and mdm.is_ch_empty(2,value):
        rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.FORWARD])
        while states['mds'][5]: time.sleep(0.1)
        print("5 has cleared")
        while not states['mds'][5]: time.sleep(0.1)
        print("5 has hit again!")
        rm.set_value_list([rm.COAST, rm.COAST, rm.FORWARD])
        while states['mds'][6]: time.sleep(0.1)
        print("6 has cleared!")
    rm.set_value(0)

# @station_operation(timeout=20.0)
# def load_ALL(**kwargs):
#     mds = states["mds"]
#     value = mdm.get_value()

#     # check if need to load L
#     if mds[0] and not mds[2]:
#         print("quick loading L")
#         rm.get_motor(0).forward()
#         while not mds[2]: time.sleep(0.1)
#         rm.get_motor(0).coast()
#         print("quick loading L done")

#     mds = states["mds"]
#     value = mdm.get_value()

#     # x x x
#     if value == 0:
#         return "nothing to do", 204
    
#     # o x x
#     if mdm.is_ch_full(0, value) and mdm.is_ch_empty(1, value):
#         rm.get_motor(0).forward()
#         while mds[0]: time.sleep(0.1)
#         rm.get_motor(1).forward()
#         while mds[2]: time.sleep(0.1)
#         rm.get_motor(0).coast()
#         while not mds[5]: time.sleep(0.1)
#         rm.get_motor(1).coast()
#     # o o x
#     elif mdm.is_ch_full(0, value) and mdm.is_ch_full(1, value) and mdm.is_ch_empty(2, value):
#         rm.get_motor(1).forward()
#         while mds[3]: time.sleep(0.1) # middle moved a bit
#         rm.get_motor(0).forward()
#         while not mds[6]: time.sleep(0.1) # right breached
#         rm.get_motor(2).forward()
#         while mds[5]: time.sleep(0.1) # middle left
#         while not mds[5] or mds[6]:
#             if not mds[2]: rm.get_motor(0).coast()
#             if mds[5]: rm.get_motor(1).coast()
#             if not mds[6]: rm.get_motor(2).coast()
#     # x o x
#     elif mdm.is_ch_full(1, value) and mdm.is_ch_empty(2, value):
#         rm.get_motor(1).forward()
#         while not mds[6]: time.sleep(0.1)
#         rm.get_motor(2).forward()
#         while mds[5]: time.sleep(0.1)
#         rm.get_motor(1).coast()
#         while mds[6]: time.sleep(0.1)
#         rm.get_motor(2).coast()
    
    
#     rm.set_value(0)





        


    
"""
x x x       -> done

o x x       ->
x o x
x x o

o o x
x o o
o x o

o o o

"""

    
    # # if middle clear, keep going
    # if mdm.is_ch_empty(1, value):
    #     rm.get_motor(1).forward()
    #     while not states[5]: time.sleep(0.1)
    
    # # if middle occupied but right is clear
    # elif mdm.is_ch_empty(2, value):
    #     rm.get_motor(1).forward()
    #     rm.get_motor(2).forward()
        

        
    
# @station_operation(timeout=20.0)
# def load_RM(**kwargs):
#     value = mdm.get_value()
#     br = True
#     if not mdm.is_ch_full(1, value):
#         print("[load_RM] M not loaded yet")
#         br = False
#     elif not mdm.is_ch_empty(2, value):
#         print("[load_RM] R is occupied")
#         br = False

#     bm = True
#     if not mdm.get_ch_bit(0,0,value):
#         print("[load_RM] nothing in L")
#         bm = False

#     if not br and not bm:
#         return "[load_RM] not doable", 409

#     if br and not bm: load_R()
#     elif bm and not br: load_M()
#     else:
#         def uno():
#             """ safer way """
#             rm.set_value_list([rm.COAST, rm.FORWARD, rm.FORWARD])
#             while not states["mds"][6]: continue # wait for [3][0] to hit to move other 
#             print("yo1")
#             rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.FORWARD])
#             while states["mds"][6]: continue # wait for [3][0] to miss to stop last
#             print("yo2")
#             rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.COAST])
#             while not states["mds"][5]: continue # wait for [2][2] to hit to stop rest
#             print("yo3")
#             rm.set_value_list([rm.COAST, rm.COAST, rm.COAST])
#             return "[load_RM] Load completed", 200
        
#         def dos():
#             """ faster way """
#             rm.set_value_list([rm.COAST, rm.FORWARD, rm.FORWARD])
#             while states["mds"][3]: continue # wait for [2][0] to miss to move other
#             print("yo1")
#             rm.set_value_list([rm.FORWARD, rm.FORWARD, rm.FORWARD])
#             while not states["mds"][6]: continue # wait for [3][0] to hit 
#             print("yo2")

#             flag1 = False
#             flag2 = False
#             flag3 = False

#             while True:
#                 if flag1 and flag2 and flag3: break
#                 if not flag1 and not states["mds"][6]: 
#                     flag1 = True
#                     rm.set_ch_value(2,rm.COAST)
#                 if not flag2 and not states["mds"][2]:
#                     flag2 = True
#                     rm.set_ch_value(0,rm.COAST)
#                 if not flag3 and states["mds"][5]:
#                     flag3 = True
#                     rm.set_ch_value(1,rm.COAST)

#             rm.set_value_list([rm.COAST, rm.COAST, rm.COAST])
#             return "[load_RM] Load completed", 200
#         return uno()

def on_load(**kwargs):
    option = kwargs.get('type', None)
    if option==None: return
    elif option=='L': load_L()
    elif option=='M': load_M()
    elif option=='R': load_R()
    elif option=='RM': load_RM() 
    elif option=='ALL': load_ALL() 
    
def on_action(action, **kwargs):
    res = None
    if secrets.MOCK: print("[station] is mock so skipping")
    elif action=="load":  on_load(**kwargs)
    elif action=="load":  on_load(**kwargs)
    elif action=="load":  on_load(**kwargs)


    return res if res is not None else ("", 200)


if __name__ == "__main__":
    try:
        load_RM()
        input("")
    finally:
        rm.set_value_list([0,0,0])