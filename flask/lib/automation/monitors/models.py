from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Iterable, Optional, List, Dict, Any
import heapq, time



# ANSI colors
RESET = "\033[0m"; RED="\033[31m"; GREEN="\033[32m"; YELLOW="\033[33m"; BLUE="\033[34m"; DIM="\033[2m"; GRAY="\033[90m"

@dataclass
class LogEvent:
    ts: datetime
    msg: str
    raw: str
    hostname: str = ""

@dataclass
class Fault:
    device: str
    severity: str  # "critical" | "warning"
    message: str

@dataclass
class MarkSuccess:
    device: str
    message: str = "success"

@dataclass
class MetaUpdate:
    device: str
    data: Dict[str, Any]

@dataclass
class ProgressUpdate:
    program: str
    current_cycle: int
    total_cycles: int
    ip: str = ""

class Action(Protocol):
    ...

@dataclass
class StartWatch:
    key: str
    timeout_s: float
    device: str
    on_timeout_msg: str
    severity: str = "critical"

@dataclass
class CancelWatch:
    key: str

@dataclass(order=True)
class _Deadline:
    when: float
    key: str = field(compare=False)
    device: str = field(compare=False)
    msg: str = field(compare=False)
    severity: str = field(compare=False)

class WatchdogManager:
    def __init__(self):
        self.heap: List[_Deadline] = []
        self.active: Dict[str, _Deadline] = {}

    def start(self, a: StartWatch):
        d = _Deadline(time.time() + a.timeout_s, a.key, a.device, a.on_timeout_msg, a.severity)
        self.active[a.key] = d
        heapq.heappush(self.heap, d)

    def cancel(self, key: str):
        self.active.pop(key, None)

    def poll_timeouts(self) -> List[Fault]:
        faults: List[Fault] = []
        now = time.time()
        while self.heap and self.heap[0].when <= now:
            d = heapq.heappop(self.heap)
            if self.active.pop(d.key, None) is not None:
                faults.append(Fault(device=d.device, severity=d.severity, message=d.msg))
        return faults
