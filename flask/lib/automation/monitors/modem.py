import re
from typing import Optional, Iterable, Dict

from lib.automation.monitors.models import LogEvent, Action, StartWatch, CancelWatch, BLUE, GREEN, DIM, RESET
from lib.automation.shared_state import SharedState


class ModemMonitor:
    id = "modem"
    re_req_cmd = re.compile(r'\bMODEM:\s*SendRemote:\s*CMD\.(?P<cmd>CONNECT|DISCONNECT)\b', re.IGNORECASE)
    re_connected    = re.compile(r'\bstate=S4_CONNECTED\b', re.IGNORECASE)
    re_disconnected = re.compile(r'\bstate=S1_IDLE\b', re.IGNORECASE)

    def __init__(self,
                 shared: SharedState,
                 connect_timeout_s: float = 20.0,
                 disconnect_timeout_s: float = 10.0,
                 verbose: bool = False,
                 meter_type: Optional[str] = None,
                 firmwares: Optional[Dict[str, str]] = None):
        self.shared = shared
        self.connect_timeout_s = connect_timeout_s
        self.disconnect_timeout_s = disconnect_timeout_s
        self.verbose = verbose
        self._connect_key: Optional[str] = None
        self._disconnect_key: Optional[str] = None

    def interested(self, msg: str) -> bool:
        m = msg.lower()
        return ("modem" in m)

    def _arm_connect(self, ev: LogEvent):
        self._connect_key = f"{self.id}:connect:{int(ev.ts.timestamp())}"
        self.shared.log(f"[{self.id}] arm CONNECT {self._connect_key} t={self.connect_timeout_s:.1f}s", color=BLUE)
        yield StartWatch(
            key=self._connect_key,
            timeout_s=self.connect_timeout_s,
            device=self.id,
            on_timeout_msg=f"Modem failed to reach CONNECTED within {self.connect_timeout_s:.1f}s"
        )

    def _arm_disconnect(self, ev: LogEvent):
        self._disconnect_key = f"{self.id}:disconnect:{int(ev.ts.timestamp())}"
        self.shared.log(f"[{self.id}] arm DISCONNECT {self._disconnect_key} t={self.disconnect_timeout_s:.1f}s", color=BLUE)
        yield StartWatch(
            key=self._disconnect_key,
            timeout_s=self.disconnect_timeout_s,
            device=self.id,
            on_timeout_msg=f"Modem failed to reach DISCONNECTED/IDLE within {self.disconnect_timeout_s:.1f}s"
        )

    def _cancel_connect(self):
        if self._connect_key:
            self.shared.log(f"[{self.id}] CONNECTED; cancel {self._connect_key}", color=GREEN)
            k = self._connect_key
            self._connect_key = None
            yield CancelWatch(k)

    def _cancel_disconnect(self):
        if self._disconnect_key:
            self.shared.log(f"[{self.id}] DISCONNECTED/IDLE; cancel {self._disconnect_key}", color=GREEN)
            k = self._disconnect_key
            self._disconnect_key = None
            yield CancelWatch(k)

    def handle(self, ev: LogEvent) -> Optional[Iterable[Action]]:
        msg = ev.msg
        self.shared.log(f"[{self.id}] Handle: {msg}", color=DIM)

        # Request CONNECT / DISCONNECT
        m = self.re_req_cmd.search(msg)
        if m:
            cmd = m.group("cmd").upper()
            if cmd == "CONNECT":
                # If a disconnect watch is pending, we can cancel it or just overwrite connect
                yield from self._arm_connect(ev)
            elif cmd == "DISCONNECT":
                # If a connect watch is pending, we can cancel it or just proceed to arm disconnect
                yield from self._arm_disconnect(ev)
            return

        # CONNECT confirmed
        if self.re_connected.search(msg):
            yield from self._cancel_connect()
            return

        # DISCONNECT confirmed
        if self.re_disconnected.search(msg):
            yield from self._cancel_disconnect()
            return
