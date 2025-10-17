# ================================================================
# File: manager.py
# ================================================================
from lib.system import last_roller_states,last_emergency_state, mds

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


