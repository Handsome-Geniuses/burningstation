# shared_state.py
import threading
from typing import Optional
from datetime import datetime
from collections import deque
import time
import os
import inspect

from lib.sse.sse_queue_manager import SSEQM


class SharedState:
    """Per-job results, cancellation, evidence, and thread-safe log routing.

    Managed jobs borrow the supervisor's writer so all workers share the meter's
    lifetime log. ``logs`` retains this job's readable evidence for DB/API use.
    Legacy/mock jobs may retain a separate buffered file. Keep logging and
    interruption changes reflected in ``lib/docs/meter/supervisor.md``.
    """
    def __init__(self):
        self.stop_event = threading.Event()
        self.abort_event = threading.Event()
        # Legacy-named shutdown flag still read by solar/keypad workers; no listener owns it.
        self.end_listener = threading.Event()
        self.disruption_event = threading.Event()
        self.meter_session = None
        self.attempt_epoch = None
        self.lifecycle_observer = False
        self.control_owner = None

        self.lock = threading.Lock()

        self.current_device = None
        self.device_results = {}
        self.device_meta = {}
        self.extras = {}

        self.logs: list[str] = []
        self._log_lock = threading.Lock()       # protects buffer + flush
        self._log_buffer = deque()              # buffered lines before write
        self._logfile_path: Optional[str] = None
        self._log_sink = None
        self._log_flush = None
        self._last_flush = time.time()
        self._flush_interval = 2.0              # seconds
        self._flush_threshold = 50              # msg lines

    def continue_after_failure(self, stop_on_fail: bool) -> bool:
        """Clear a subtest's stop signal only when no external abort was requested."""
        with self.lock:
            if stop_on_fail or self.abort_event.is_set() or self.disruption_event.is_set():
                return False
            self.stop_event.clear()
            self.extras.pop("mock_failure", None)
            self.extras.pop("operator_failure", None)
            return True

    def broadcast_progress(self, ip: str, program: str, current_cycle: int, total_cycles: int):
        """Broadcast progress updates during test cycles."""
        self.extras["progress"] = {"current": current_cycle, "total": total_cycles}
        SSEQM.broadcast("progress", {
            "ip": ip,
            "program": program,
            "current_cycle": current_cycle,
            "total_cycles": total_cycles
        })

    #----- Logging methods -----#
    @property
    def logfile_path(self) -> Optional[str]:
        return self._logfile_path

    def set_logfile(self, path: Optional[str]):
        """Select a legacy per-job file; managed jobs use set_session_log instead."""
        self.flush_logs()
        self._log_sink = self._log_flush = None
        self._logfile_path = path
        if not path:
            return

        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.log("=== LOG STARTED ===", console=False)

    def set_session_log(self, supervisor):
        """Borrow the open lifetime log; ending a job must never close/truncate it.

        logfile_path still identifies the file for robot log-correlation APIs.
        """
        self.flush_logs()
        with self._log_lock:
            self._logfile_path = supervisor.log_path
            self._log_sink = supervisor.write_line
            self._log_flush = supervisor.flush_log

    def log(self, message: str, *, console: bool = False, color: str = '', source=None, persist=True):
        """
        Thread-safe logging.
        - Always appends to in-memory self.logs
        - Managed output goes immediately through the supervisor's locked writer
        - Legacy output buffers; persist=False keeps already-saved journal lines
          in job evidence without duplicating them in the lifetime file
        - Optional console echo
        """
        frame = inspect.currentframe()
        try:
            caller = frame.f_back.f_back  # Direct caller of log()
            if caller:
                filename = os.path.basename(caller.f_code.co_filename)
                funcname = caller.f_code.co_name
                caller_tag = f"{filename}.{funcname}"
            else:
                caller_tag = "unknown"
        finally:
            del frame

        if source is not None:
            caller_tag = source
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        line = f"[{timestamp}] {caller_tag}: {message}"

        with self._log_lock:
            self.logs.append(line)
            if persist and self._log_sink is not None:
                self._log_sink(line)
            elif persist and self._logfile_path:
                self._log_buffer.append(line)

            # Conditional flush
            should_flush = (
                len(self._log_buffer) >= self._flush_threshold or
                time.time() - self._last_flush >= self._flush_interval
            )
            if should_flush:
                self._flush_buffer()

        if console:
            s = f"{color}{line}\033[0m" if color else line
            print(s)

    def _flush_buffer(self):
        """Internal: write buffered lines to disk"""
        if not self._log_buffer or not self._logfile_path:
            return

        try:
            with open(self._logfile_path, 'a', encoding='utf-8') as f:
                while self._log_buffer:
                    f.write(self._log_buffer.popleft() + '\n')
                f.flush()  # Ensure OS writes to disk
            self._last_flush = time.time()
        except Exception as e:
            print(f"Failed to write to {self._logfile_path}: {e}")

    def flush_logs(self):
        """Flush job output without closing the borrowed supervisor writer."""
        with self._log_lock:
            self._flush_buffer()
            if self._log_flush:
                self._log_flush()
