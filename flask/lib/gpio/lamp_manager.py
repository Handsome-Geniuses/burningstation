from lib.gpio.gpio_setup import pwm_lamps
from lib.system.states import states
from lib.sse.sse_queue_manager import SSEQM, key_payload
from pipwm import HWPWM


pwm = [HWPWM(ch) for ch in pwm_lamps]
amnt = len(pwm)
for p in pwm: 
    p.export = 1
    p.hz = 100
    p.dc = 50

def __broadcast_change():
    SSEQM.broadcast("state", key_payload("lamp", states['lamp']))

def get_value_list():
    # return [pwm[0].enable, pwm[1].enable, pwm[0].dc, pwm[1].dc]
    return [getattr(o, p) for p in ['enable','dc'] for o in pwm]

def lamp(l:int,state:bool|None=None, dc:int|None=None):
    assert 0 <= l < amnt, f"l must be between 0 and {amnt}"
    assert dc==None or 0 <= dc <= 100, f"dc should be 0-100. Got {dc}"
    change = False
    if state is not None and states['lamp'][l]!=state:
        pwm[l].enable = state
        states['lamp'][l] = state
        change = True
    if dc is not None and states['lamp'][l+amnt]!=dc:
        pwm[l].dc = dc
        states['lamp'][l+amnt]=dc
        change = True
    if change: __broadcast_change()


