import re
from typing import Optional, Iterable, Dict
from lib.automation.monitors.models import LogEvent, Action, StartWatch, CancelWatch, BLUE, GREEN, YELLOW, RED, DIM, RESET


class PrinterMonitor:
    id = "printer"
    re_start  = re.compile(r'IPSBusDevSendPrintMessageVA', re.IGNORECASE)
    re_result = re.compile(r'PRINT_TICKET_REPLY:.*result=([A-Z]+)', re.IGNORECASE)
    re_status = re.compile(r'PRINTER_STATUS_REPLY:', re.IGNORECASE)

    def __init__(self,
                 timeout_s: float = 8.0,
                 verbose: bool = False,
                 meter_type: Optional[str] = None,
                 firmwares: Optional[Dict[str, str]] = None):
        self.timeout_s = timeout_s
        self.verbose = verbose
        self._last_job_key: Optional[str] = None

    def interested(self, msg: str) -> bool:
        m = msg.lower()
        return ("print" in m)

    def handle(self, ev: LogEvent) -> Optional[Iterable[Action]]:
        msg = ev.msg
        if self.verbose:
            print(f"{DIM}[{self.id}] Handle: {msg}{RESET}")

        # Request PRINT
        if self.re_start.search(msg):
            key = f"{self.id}:{int(ev.ts.timestamp())}"
            self._last_job_key = key
            if self.verbose:
                print(f"{BLUE}[{self.id}] arm {key} t={self.timeout_s:.1f}s{RESET}")
            yield StartWatch(key=key, timeout_s=self.timeout_s, device=self.id,
                             on_timeout_msg=f"Print timed out after {self.timeout_s:.1f}s")
            return

        # SUCCESS / FAIL confirmed
        if self.re_result.search(msg):
            m = self.re_result.search(msg); result = (m.group(1) if m else "").upper()
            if self._last_job_key:
                if result == "SUCCEEDED":
                    if self.verbose:
                        print(f"{GREEN}[{self.id}] success; cancel {self._last_job_key}{RESET}")
                    yield CancelWatch(self._last_job_key)
                elif result == "PENDING":
                    if self.verbose:
                        print(f"{RED}[{self.id}] PENDING; cancel {self._last_job_key} and fault now{RESET}")
                    yield CancelWatch(self._last_job_key)
                    yield StartWatch(key=f"{self.id}:fail:{int(ev.ts.timestamp())}",
                                     timeout_s=0.0, device=self.id,
                                     on_timeout_msg="Printer returned PENDING (failure).")
                else:
                    if self.verbose:
                        print(f"{YELLOW}[{self.id}] unknown result={result}; cancel {self._last_job_key}{RESET}")
                    yield CancelWatch(self._last_job_key)
            return

        if self.re_status.search(msg):
            # Helpful for UI/logs; no watches modified
            return
