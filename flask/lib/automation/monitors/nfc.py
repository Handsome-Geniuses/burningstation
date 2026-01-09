import re
from typing import Optional, List, Iterable, Dict

from lib.automation.monitors.models import LogEvent, Action, StartWatch, CancelWatch, BLUE, GREEN, DIM, RESET
from lib.automation.shared_state import SharedState


class NFCMonitor:
    id = "nfc"
    re_req_any = re.compile(
        r'GENERIC_TERMINAL\.\S*->KIOSK_NFC\.\S*\s+(?:APPLICATION_MSG\s+)?'
        r'(?P<verb>EMV_POWER|CARD_READ_INST)\b.*?\bD=(?P<payload>[0-9A-Fa-f ]+)',
        re.IGNORECASE
    )
    re_reply = re.compile(r'\bEMV_POWER_REPLY\b.*?\bD=(?P<payload>[0-9A-Fa-f ]+)', re.IGNORECASE)
    re_ui_payload = re.compile(r'\bEMV_UI_OUTPUT\b.*?\bD=(?P<payload>[0-9A-Fa-f ]+)', re.IGNORECASE)

    def __init__(self,
                 shared: SharedState,
                 timeout_on_s: float = 6.0,
                 timeout_off_s: float = 3.0,
                 verbose: bool = False,
                 meter_type: Optional[str] = None,
                 firmwares: Optional[Dict[str, str]] = None):
        self.shared = shared
        self.timeout_on_s = timeout_on_s
        self.timeout_off_s = timeout_off_s
        self.verbose = verbose
        self._on_key: Optional[str] = None
        self._off_key: Optional[str] = None

    def interested(self, msg: str) -> bool:
        m = msg.lower()
        return ("kiosk_nfc" in m) or ("emv_power" in m) or ("card_read_inst" in m) or ("emv_power_reply" in m)

    @staticmethod
    def _tokens(hex_blob: str) -> List[str]:
        return [t.strip().upper() for t in hex_blob.split() if t.strip()]

    @staticmethod
    def _hex_to_bytes(hex_blob: str) -> bytes:
        return bytes.fromhex("".join(hex_blob.split()))

    @staticmethod
    def _contains_ascii(hex_blob: str, *needles: bytes) -> bool:
        p = NFCMonitor._hex_to_bytes(hex_blob).upper()
        return any(n.upper() in p for n in needles)

    def _start_on_watch(self, ev: LogEvent):
        self._on_key = f"{self.id}:on:{int(ev.ts.timestamp())}"
        self.shared.log(f"[{self.id}] arm ON {self._on_key} t={self.timeout_on_s:.1f}s", color=BLUE)
        yield StartWatch(
            key=self._on_key,
            timeout_s=self.timeout_on_s,
            device=self.id,
            on_timeout_msg=f"NFC failed to power ON within {self.timeout_on_s:.1f}s"
        )

    def _start_off_watch(self, ev: LogEvent):
        self._off_key = f"{self.id}:off:{int(ev.ts.timestamp())}"
        self.shared.log(f"[{self.id}] arm OFF {self._off_key} t={self.timeout_off_s:.1f}s", color=BLUE)
        yield StartWatch(
            key=self._off_key,
            timeout_s=self.timeout_off_s,
            device=self.id,
            on_timeout_msg=f"NFC failed to power OFF within {self.timeout_off_s:.1f}s"
        )

    def _cancel_on(self):
        if self._on_key:
            self.shared.log(f"[{self.id}] ON confirmed; cancel {self._on_key}", color=GREEN)
            k = self._on_key
            self._on_key = None
            yield CancelWatch(k)

    def _cancel_off(self):
        if self._off_key:
            self.shared.log(f"[{self.id}] OFF confirmed; cancel {self._off_key}", color=GREEN)
            k = self._off_key
            self._off_key = None
            yield CancelWatch(k)

    def _decode_emv_power_reply(self, toks: List[str]) -> Optional[str]:
        """
        Return 'on', 'off', or None based on EMV_POWER_REPLY payload tokens.
        Supports:
          MS2.5 (2 bytes):  ON=01 00, OFF=00 00
          MSX   (4 bytes):  ON=01 01 00 00, OFF=01 00 00 00
        """
        n = len(toks)
        if n < 2:
            return None

        # 2-byte variant
        if n == 2:
            if toks[0] == "01" and toks[1] == "00":
                return "on"
            if toks[0] == "00" and toks[1] == "00":
                return "off"
            return None

        # 4+ byte variant: first byte looks like module id (01), second byte is state
        if toks[0] == "01":
            if toks[1] == "01":
                return "on"
            if toks[1] == "00":
                return "off"
        return None

    def handle(self, ev: LogEvent) -> Optional[Iterable[Action]]:
        msg = ev.msg
        self.shared.log(f"[{self.id}] Handle: {msg}", color=DIM)

        # Request ON / OFF
        m = self.re_req_any.search(msg)
        if m:
            verb = m.group("verb").upper()
            toks = self._tokens(m.group("payload"))
            self.shared.log(f"[{self.id}] request {verb} D={' '.join(toks)}", color=BLUE)

            if verb == "EMV_POWER":
                # ON: 01 01 ...   OFF: 01 00 ...
                if len(toks) >= 2 and toks[0] == "01":
                    if toks[1] == "01":
                        yield from self._start_on_watch(ev)
                    elif toks[1] == "00":
                        yield from self._start_off_watch(ev)
            elif verb == "CARD_READ_INST":
                # ON: 00 02 ...   OFF: 00 05 ...
                if len(toks) >= 2 and toks[0] == "00":
                    if toks[1] == "02":
                        yield from self._start_on_watch(ev)
                    elif toks[1] == "05":
                        yield from self._start_off_watch(ev)
            return

        # ON / OFF confirmed
        m = self.re_reply.search(msg)
        if m:
            toks = self._tokens(m.group("payload"))
            self.shared.log(f"[{self.id}] reply EMV_POWER_REPLY ({len(toks)} bytes) D={' '.join(toks)}", color=DIM)

            state = self._decode_emv_power_reply(toks)
            if state == "on":
                yield from self._cancel_on()
                return
            if state == "off":
                yield from self._cancel_off()
                return
        
        # --- 3) (Optional) UI lines: keep for future; not used for cancel here
        # m = self.re_ui_payload.search(msg)
        # if m:
        #     hex_blob = m.group("payload")
        #     # If you decide to early-cancel on UI later, you can decode and check substrings here.
