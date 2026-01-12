from __future__ import annotations
import os, re, time, json, threading
import paramiko
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Iterable, Any

from lib.automation.monitors.models import (
    LogEvent, Fault, StartWatch, CancelWatch, WatchdogManager, MarkSuccess, MetaUpdate,
    ProgressUpdate, Action, RESET, RED, GREEN, YELLOW, BLUE, DIM, GRAY
)
from lib.automation.shared_state import SharedState
from lib.automation.monitors import create_monitor


RE_FALLBACK = re.compile(r'^(\w+\s+\d+\s+\d+:\d+:\d+)\s+\S+\s+MS3\[\d+\]:\s*(.*)')
USELESS_RES = [
    re.compile(r'^WebKitLib:WebKitSetURL:\d+: URL=http://127\.0\.0\.1:8005/UIPage\.php'),
    re.compile(r'^WebKitLib:WebKitRefresh:\d+: Refresh'),

    re.compile(r'^MS3Queue:MS3QGetAndProcessMessage:\d+: Got type=(?:IPSBUS|TIMER|SAGENT)'),
    re.compile(r'^MS3Queue:MS3QGetAndProcessMessage:.*Unhandled message: IPSBUS'),

    re.compile(r'^TimerLib:TimerSetTimer:\d+: Set ref='),
    re.compile(r'^TimerLib:sTimerWorkerThread:\d+: Expired ref='),

    re.compile(r'^UXAppUtils:UXLog:\d+: *-> *UXAppDrawDisplay'),
    re.compile(r'^UXAppUtils:UXLog:\d+: *<- *UXMeterInvalidateAppDisplay'),
    re.compile(r'^UXAppUtils:UXLog:\d+: *<- *UXMeterGetTime:'),

    re.compile(r'^MS3:sSigThreadMain:\d+: Caught signal 17 \(Child exited\)'),
    re.compile(r'^MS3:sSigThreadMain:\d+: Caught and ignore SIGCHLD'),
]

class Listener:
    def __init__(self,
                 shared: SharedState,
                 host: str = "192.168.5.61",
                 user: str = "root",
                 pswd: str = "",
                 save_logs: bool = True,
                 verbose: bool = False,
                 trace_lines: bool = False,
                 **kwargs
                 ):
        self.shared = shared
        self.host, self.user, self.pswd = host, user, pswd
        self.save_logs, self.verbose, self.trace_lines = save_logs, verbose, trace_lines
        
        log_dir = "./assets/logs" if os.name == "nt" else "./logs"
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # self.logfile_path = os.path.join(log_dir, f"{self.host}_{ts}.txt")
        self.logfile_path = os.path.join(log_dir,kwargs.pop("logfile_name", f"{self.host}_{ts}")+'.log')

        self.devs: Dict[str, Any] = {}
        self.wd = WatchdogManager()

    # ---- Device registration ----
    def register(self, dev) -> None:
        self.devs[getattr(dev, "id")] = dev

    # ---- SSH + journalctl stream ----
    def _open_ssh(self):
        cmd = f'journalctl -u MS3_Platform.service -f -n0 -o json'
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # self.shared.log(f"connecting {self.user}@{self.host}", color=DIM)

        client.connect(self.host, username=self.user, password=self.pswd)
        self.shared.log(f"connected; running: {cmd}", color=DIM)

        stdin, stdout, stderr = client.exec_command(cmd)
        return client, stdout

    # ---- JSON line -> LogEvent ----
    def _parse_line(self, line: str) -> Optional[LogEvent]:
        try:
            j = json.loads(line)
            ts_raw = j.get("__REALTIME_TIMESTAMP", "")
            hostname = j.get("_HOSTNAME", "")
            msg = j.get("MESSAGE", "")

            if ts_raw:
                ts = datetime.fromtimestamp(int(ts_raw) / 1_000_000)
            else:
                ts = datetime.now()
            return LogEvent(ts=ts, msg=msg, raw=line.rstrip("\n"), hostname=hostname)
        except Exception:
            # fallback try
            m = RE_FALLBACK.match(line)
            if not m:
                return None
            dt_str, msg = m.groups()
            try:
                ts = datetime.strptime(dt_str, "%b %d %H:%M:%S")
            except Exception:
                ts = datetime.now()
            return LogEvent(ts=ts, msg=msg, raw=line.rstrip("\n"), hostname="")

    # ---- Human readable log line ----
    @staticmethod
    def _format_human(ev: LogEvent) -> str:
        ts_str = ev.ts.strftime("%b %d %H:%M:%S")
        # host = ev.hostname or "UNKNOWN"
        msg = (ev.msg or "").replace("\n", " ").strip()
        # return f"[{ts_str}] [{host}] | {msg}"
        return msg

    def _log_to_file(self, text:str) -> None:
        self.shared.log(text)

    def _is_useless(self, ev) -> bool:
        msg = (ev.msg or '').strip()
        for rx in USELESS_RES:
            if rx.search(msg):
                return True
        return False

    def _emit_faults(self, faults: List[Fault]) -> None:
        if not faults:
            return
        for f in faults:
            color = RED if f.severity == "critical" else YELLOW
            self.shared.log(f"[FAULT] {f.device}: {f.message}", console=self.verbose, color=color)
            dev_name = getattr(self.shared, "current_device", None) or f.device
            if dev_name:
                self.shared.device_results[dev_name] = 'fail'
        if any(f.severity == "critical" for f in faults):
            self.shared.stop_event.set()

    def _process_action(self, a: Action, dev_id: str) -> None:
        allowed = self.shared.allowed_monitors
        is_allowed = dev_id in allowed

        if isinstance(a, StartWatch):
            if is_allowed:
                self.wd.start(a)
                self.shared.log(f"[{dev_id}] watch start {a.key} ({a.timeout_s}s)", console=self.verbose, color=BLUE)
            else:
                self.shared.log(f"[SUPPRESS][{dev_id}] watch start {a.key} ({a.timeout_s}s)", console=self.verbose, color=YELLOW)

        elif isinstance(a, CancelWatch):
            if is_allowed:
                self.wd.cancel(a.key)
                self.shared.log(f"[{dev_id}] watch cancel {a.key}", console=self.verbose, color=DIM)
            else:
                self.shared.log(f"[SUPPRESS][{dev_id}] watch cancel {a.key}", console=self.verbose, color=YELLOW)

        elif isinstance(a, MarkSuccess):
            if is_allowed:
                self.shared.log(f"[{a.device}] success: {a.message}", console=self.verbose, color=GREEN)
                self.shared.device_results[a.device] = "pass"
                if hasattr(self.shared, "success_event"):
                    self.shared.success_event.set()
            else:
                self.shared.log(f"[SUPPRESS][{a.device}] success: {a.message}", console=self.verbose, color=YELLOW)

        elif isinstance(a, MetaUpdate):
            if is_allowed:
                for k, v in (a.data or {}).items():
                    self.shared.device_meta[k] = v
            else:
                self.shared.log(f"[SUPPRESS][{dev_id}] meta: {a.data}", console=self.verbose, color=YELLOW)

        elif isinstance(a, ProgressUpdate):
            if is_allowed:
                ip = a.ip or self.host
                self.shared.broadcast_progress(
                    ip, a.program, a.current_cycle, a.total_cycles
                )
            else:
                self.shared.log(f"[SUPPRESS][{dev_id}] progress: {a.current_cycle}/{a.total_cycles}", console=self.verbose, color=YELLOW)

    # ---- Main loop ----
    def run(self) -> None:
        client, stdout = self._open_ssh()
        try:
            for line in iter(stdout.readline, ""):
                if not line:
                    time.sleep(0.05)
                    continue

                # Check and process any _pending_actions
                pending_actions = []
                with self.shared.lock:
                    pending_actions = self.shared.__dict__.pop("_pending_actions", [])
                for a in pending_actions:
                    dev_id = getattr(a, "device", None) or "unknown"
                    self._process_action(a, dev_id)

                if self.shared.stop_event.is_set() or self.shared.end_listener.is_set():
                    break

                ev = self._parse_line(line)
                if not ev:
                    continue

                if self.save_logs and not self._is_useless(ev):
                    self._log_to_file(self._format_human(ev))

                # if self.trace_lines and self.verbose:
                #     print(f"{GRAY}[line] {ev.msg}{RESET}")

                # fan-out to registered monitors
                for dev in list(self.devs.values()):
                    interested_fn = getattr(dev, "interested", None)

                    # Check if monitor is interested in this event
                    try:
                        is_interested = True if interested_fn is None else bool(interested_fn(ev.msg))
                    except Exception as e:
                        self.shared.log(f"[{dev.id}] interested() error: {e}", console=True, color=YELLOW)
                        continue

                    if not is_interested:
                        continue

                    # Run the monitor and collect its actions
                    try:
                        actions = list((getattr(dev, "handle", lambda _ : [])(ev)) or [])
                    except Exception as e:
                        self.shared.log(f"[{dev.id}] handle() error: {e}", console=True, color=YELLOW)
                        continue

                    # Apply or suppress actions depending on allow-list
                    for a in actions:
                        self._process_action(a, dev.id)

                # poll watchdogs
                faults = self.wd.poll_timeouts()
                self._emit_faults(faults)

        finally:
            stdout.channel.close()
            client.close()
            self.shared.log(f"End of listener.run() main loop", color=DIM)


# --- Helper to start a listener thread for a job ---
def start_listener_thread(shared,
                          host: str,
                          pswd: str,
                          devices: List[Tuple[str, Dict[str, Any]]],
                          user: str = "root",
                          save_logs: bool = True,
                          verbose: bool = False,
                          trace_lines: bool = False,
                          **kkwargs
                          ) -> threading.Thread:
    lst = Listener(shared=shared, host=host, user=user, pswd=pswd, save_logs=save_logs,
                   verbose=verbose, trace_lines=trace_lines, **kkwargs)
    for dev_id, kwargs in devices:
        dev = create_monitor(dev_id, shared=shared, verbose=verbose, **kwargs)
        lst.register(dev)

    t = threading.Thread(target=lst.run, name=f"listener-{host}", daemon=True)
    t.start()
    return t




# --- Standalone runner for quick ad-hoc testing ---
if __name__ == "__main__":
    import threading as _t, time as _time

    HOST = "192.168.4.33"
    USER = "root"
    PSWD = "handsome"
    SAVE_LOGS = True
    VERBOSE = True
    TRACE_LINES = False

    # Edit here to choose devices and kwargs
    DEVICES = [
        # ("printer", {"timeout_s": 8.0}),
        # ("nfc", {"timeout_on_s": 6.0, "timeout_off_s": 3.0}),
        # ("modem", {"connect_timeout_s": 25.0, "disconnect_timeout_s": 20.0}),
        # ("keypad", {"inactivity_timeout_s": 8.0, "count": 1}),
        ("nfc_read", {"timeout_on_s": 6.0, "timeout_off_s": 3.0}),
    ]

    # Minimal SharedState fallback
    try:
        from shared_state import SharedState as _Shared
    except Exception:
        class _Shared:
            def __init__(self):
                self.stop_event = _t.Event()
                self.end_listener = _t.Event()
                self.lock = _t.Lock()

    shared = _Shared()

    print("\n[listener] starting…")
    t = start_listener_thread(
        shared=shared,
        host=HOST,
        pswd=PSWD,
        devices=DEVICES,
        user=USER,
        save_logs=SAVE_LOGS,
        verbose=VERBOSE,
        trace_lines=TRACE_LINES,
    )

    try:
        while t.is_alive():
            _time.sleep(0.25)
            if shared.stop_event.is_set():
                break
    except KeyboardInterrupt:
        print("\n[listener] Ctrl+C received, shutting down…")
    finally:
        shared.end_listener.set()
        shared.stop_event.set()
        t.join(timeout=2.0)
        print("[listener] stopped.")
