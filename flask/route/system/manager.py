# ================================================================
# File: manager.py
# Desc: handle logic
# ================================================================
import threading
import time
from lib.sse_queue_manager import sseq, SSEQueue

__test_count = 0

def test_message():
    global __test_count
    __test_count = __test_count + 1
    sseq.broadcast("test", __test_count)


def event_stream():
    queue = SSEQueue()
    sseq.append(queue)
    try:
        while True:
            # block until a payload is available
            yield queue.pop_payload()
    finally:
        sseq.remove(queue)


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


# threading.Thread(target=__interval_task, daemon=True).start()
def start_interval_task():
    global __interval_thread_started
    if not __interval_thread_started:
        threading.Thread(target=__interval_task, daemon=True).start()
        __interval_thread_started = True


start_interval_task()
