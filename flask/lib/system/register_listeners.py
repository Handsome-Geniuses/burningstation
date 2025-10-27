from lib.gpio import *
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.system.states import states
from lib.utils import secrets

states['emergency'] = emergency.state
states['motors'] = rm.get_value_list()
states['mds'] = mdm.get_state()

# =============================================================
# emergency!
# =============================================================
def emergency_event(p: HWGPIO):
    if secrets.VERBOSE:
        print(f"[listener] p{p.gpio} -- {p.state}")
    if states["emergency"] == p.state:
        return
    states["emergency"] = p.state
    if p.state:
        rm.set_value(0)
        states["running"] = False
    SSEQM.broadcast("state", key_payload("emergency", p.state))
    
HWGPIO_MONITOR.add_listener(emergency, emergency_event)

# =============================================================
# interrupt for meter detection manager
# =============================================================
mds = mdm.get_mds()
def mds_event_builder(p: HWGPIO, index: int):
    def handler(p: HWGPIO):
        if secrets.VERBOSE:
            print(f"[listener] p{p.gpio} -- {p.state}")
        if p.state == states.get("mds", [None] * 9)[index]:
            return
        states["mds"][index] = p.state
        SSEQM.broadcast("state", key_payload("mds", states["mds"]))
    return handler

for i, md in enumerate(mds):
    HWGPIO_MONITOR.add_listener(md, mds_event_builder(md, i))

