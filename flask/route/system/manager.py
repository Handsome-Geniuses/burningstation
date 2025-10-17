# ================================================================
# File: manager.py
# Desc: handle logic
# ================================================================
import json
import threading
from lib.sse.question import setResponse
from lib.sse.register_listeners import last_roller_states,last_emergency_state, mds

from lib.sse import (
    SSEQueue,
    dump_sse_payload,
    SSEQM,
    event_stream as _estream,
    sse_payload,
)

__test_count = 0


def test_message():
    global __test_count
    __test_count = __test_count + 1
    SSEQM.broadcast("test", __test_count)


def initial_payloads():
    data = {
        "mds": mds.states,
        "rollersMoving": last_roller_states,
        "emergency": last_emergency_state
    }
    for k, v in data.items():
        yield dump_sse_payload(sse_payload("state", {"key": k, "value": v}))


def event_stream():
    # send initial data
    yield from initial_payloads()

    # registered!
    yield from _estream()


def __interval_task():
    count = 0
    while True:
        # reset every 24hr
        if (count := count + 1) >= 86400:
            count = 0
        try:
            # 10 minute
            if count % 600:
                pass
        except:
            pass


__interval_thread_started = False

def start_interval_task():
    global __interval_thread_started
    if not __interval_thread_started:
        threading.Thread(target=__interval_task, daemon=True).start()
        __interval_thread_started = True


start_interval_task()
