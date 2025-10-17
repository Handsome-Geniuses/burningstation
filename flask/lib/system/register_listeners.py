from lib.gpio import *
from lib.sse.sse_queue_manager import SSEQM, key_payload

# ==========================================
# rollers
# ==========================================
last_roller_states = [p.state for p in rollers]

# just broadcasts if roller is moving
def roller_event(p: HWGPIO):
    # print(f"roller{p.gpio} --> {p.state}")
    idx = rollers.index(p)
    if idx is None:
        return
    if last_roller_states[idx] == p.state:
        return
    last_roller_states[idx] = p.state
    # payload = {"key": "rollersMoving", "value": __roller_states}
    # SSEQM.broadcast("state", payload)
    SSEQM.broadcast("state", key_payload("rollersMoving", last_roller_states))


for p in rollers:
    # HWGPIO_MONITOR.add_listener(p, roller_event)
    p.out_cb = roller_event

def pcfio1_event(p:HWGPIO):
    if not p.state:
        bits = pcfio1.byte
        if (mds.value&~(1 << 8))==bits: return
        mds.value = bits
        SSEQM.broadcast("state", key_payload("mds", mds.states)) 
def pcfio2_event(p:HWGPIO):
    if not p.state:
        b = pcfio2.byte & 0b1
        if b and mds.get_bit(8): return
        mds.set_bit(8, b)
        SSEQM.broadcast("state", key_payload("mds", mds.states)) 
HWGPIO_MONITOR.add_listener(pcfio1_int, pcfio1_event)        
HWGPIO_MONITOR.add_listener(pcfio2_int, pcfio2_event)


# ==========================================
# emergency!
# ==========================================
__intial_estate = emergency.state
last_emergency_state = __intial_estate
def emergency_event(p: HWGPIO):
    # print(f"emergency={p.state}")
    global last_emergency_state
    if p.state == last_emergency_state: return
    last_emergency_state = p.state
    SSEQM.broadcast("state", key_payload("emergency", p.state))
HWGPIO_MONITOR.add_listener(emergency,emergency_event)

    