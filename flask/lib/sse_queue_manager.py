from typing import Any, Optional, TypedDict, List
from collections import deque
import json
import threading


# Typed payload
class SSEPayload(TypedDict):
    event: str
    payload: Any


def build_payload(event: str, payload: Any) -> SSEPayload:
    return {"event": event, "payload": payload}


# Thread-safe queue for a single client
class SSEQueue:
    def __init__(self):
        self.queue = deque()
        self.cond = threading.Condition()

    def add_payload(self, payload: SSEPayload):
        msg = f"data: {json.dumps(payload)}\n\n"
        with self.cond:
            self.queue.append(msg)
            self.cond.notify()  # wake any waiting generator

    def pop_payload(self) -> str:
        with self.cond:
            while not self.queue:
                self.cond.wait()  # block until a message is available
            return self.queue.popleft()


class SSEQueueManager:
    _instance: Optional["SSEQueueManager"] = None
    queues: list["SSEQueue"]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.queues = []
        return cls._instance

    def append(self, q: SSEQueue):
        self.queues.append(q)

    def remove(self, q: SSEQueue):
        self.queues.remove(q)

    def broadcast_payload(self, payload: SSEPayload):
        for q in self.queues:
            q.add_payload(payload)

    def broadcast(self, event: str, payload: Any):
        if event != "keep-alive":
            print(f"[DEBUG] broadcast(event={event}, payload={payload})")
        self.broadcast_payload(build_payload(event, payload))


sseq = SSEQueueManager()
