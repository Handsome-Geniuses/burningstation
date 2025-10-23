# ================================================================
# File: manager.py
# ================================================================
from lib.system import states

from lib.sse import (
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
    for k, v in states.items():
        yield dump_sse_payload(sse_payload("state", {"key": k, "value": v}))


def event_stream():
    # send initial data
    yield from initial_payloads()

    # registered!
    yield from _estream()


