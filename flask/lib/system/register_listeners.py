from lib.gpio import HWGPIO, HWGPIO_MONITOR, emergency, rm, mdm
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.system.bay_guess import empty_bay_guess, infer_bay_guess_from_mds
from lib.system.states import states
from lib.utils import secrets
from prettyprint import STYLE, prettyprint as print

# =============================================================
# emergency!
# =============================================================
def emergency_event(p: HWGPIO):
    if secrets.VERBOSE:
        print(f"⚡[listener] p{p.gpio} -- {p.state}", fg="#ffaa00", style=STYLE.DIM)
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
            print(f"⚡[listener] p{p.gpio} -- {p.state}", style=STYLE.DIM)
        if p.state == states.get("mds", [None] * 9)[index]:
            return
        states["mds"][index] = p.state
        from lib.meter.meter_manager import METERMANAGER as mm

        states["bayGuess"] = infer_bay_guess_from_mds(
            states.get("bayGuess", empty_bay_guess()),
            states["mds"],
            states.get("motors"),
            mm.meters.keys(),
        )
        SSEQM.broadcast("state", key_payload("mds", states["mds"]))
        SSEQM.broadcast("state", key_payload("bayGuess", states["bayGuess"]))
    return handler

for i, md in enumerate(mds):
    HWGPIO_MONITOR.add_listener(md, mds_event_builder(md, i))
