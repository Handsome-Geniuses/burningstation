from lib.utils import secrets
from typing import Any, Optional, TypedDict, List
from collections import deque
import json
import threading


# Typed payload
class SSEPayload(TypedDict):
    event: str
    payload: Any


class KeyPayload(TypedDict):
    key: str
    value: any


def key_payload(key: str, value: any):
    return {"key": key, "value": value}


def sse_payload(event: str, payload: Any) -> SSEPayload:
    return {"event": event, "payload": payload}


def dump_sse_payload(payload: SSEPayload):
    return f"data: {json.dumps(payload)}\n\n"


# Thread-safe queue for a single client
class SSEQueue:
    def __init__(self):
        self.queue = deque()
        self.cond = threading.Condition()

    def add_payload(self, payload: SSEPayload):
        # msg = f"data: {json.dumps(payload)}\n\n"
        with self.cond:
            self.queue.append(dump_sse_payload(payload))
            self.cond.notify()  # wake any waiting generator

    def pop_payload(self) -> str:
        with self.cond:
            while not self.queue:
                self.cond.wait()  # block until a message is available
            return self.queue.popleft()


# class SSEQueueManager:
#     _instance: Optional["SSEQueueManager"] = None
#     queues: list["SSEQueue"]
#     verbose: bool

#     def __new__(cls):
#         if cls._instance is None:
#             cls._instance = super().__new__(cls)
#             cls._instance.queues = []
#             cls._instance.verbose = False
#         return cls._instance

#     def append(self, q: SSEQueue):
#         self.queues.append(q)

#     def remove(self, q: SSEQueue):
#         self.queues.remove(q)

#     def broadcast_payload(self, payload: SSEPayload):
#         for q in self.queues:
#             q.add_payload(payload)

#     def broadcast(self, event: str, payload: Any):
#         if event != "keep-alive":
#             if self.verbose:
#                 print(f"[DEBUG] broadcast(event={event}, payload={payload})")
#         self.broadcast_payload(sse_payload(event, payload))


# sseq = SSEQueueManager()


class SSEQM:
    queues: list["SSEQueue"] = []
    verbose: bool = False

    @classmethod
    def append(cls, q: SSEQueue):
        cls.queues.append(q)

    @classmethod
    def remove(cls, q: SSEQueue):
        cls.queues.remove(q)

    @classmethod
    def broadcast_payload(cls, payload: SSEPayload):
        for q in cls.queues:
            q.add_payload(payload)

    @classmethod
    def broadcast(cls, event: str, payload: Any):
        if event != "keep-alive":
            if cls.verbose:
                print(f"[DEBUG] broadcast(event={event}, payload={payload})")
        cls.broadcast_payload(sse_payload(event, payload))


def event_stream():
    queue = SSEQueue()
    SSEQM.append(queue)
    try:
        while True:
            # block until a payload is available
            yield queue.pop_payload()
    finally:
        SSEQM.remove(queue)
