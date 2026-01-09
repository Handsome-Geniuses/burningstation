# shared_state.py
import threading
from typing import Any
from datetime import datetime
from collections import deque
import time
import os
import inspect

from lib.sse.sse_queue_manager import SSEQM


class SharedState:
    def __init__(self):
        self.stop_event = threading.Event()
        self.end_listener = threading.Event()
        self.success_event = threading.Event()

        self.lock = threading.Lock()

        self.current_device = None
        self.device_results = {}
        self.device_meta = {}
        self.allowed_monitors: set[str] = set()
        self.extras = {}

        self.logs: list[str] = []
        self._log_lock = threading.Lock()       # protects buffer + flush
        self._log_buffer = deque()              # buffered lines before write
        self._logfile_path: str | None = None
        self._last_flush = time.time()
        self._flush_interval = 2.0              # seconds
        self._flush_threshold = 50              # msg lines

    def set_allowed(self, devices: set[str], reason: str = ""):
        self.allowed_monitors = devices
        self.log(f"allowed_monitors set to {devices} {('- ' + reason) if reason else ''}")

    def broadcast_progress(self, ip: str, program: str, current_cycle: int, total_cycles: int):
        """Broadcast progress updates during test cycles."""
        SSEQM.broadcast("progress", {
            "ip": ip,
            "program": program,
            "current_cycle": current_cycle,
            "total_cycles": total_cycles
        })

    def queue_action(self, action: Any):
        """
        Thread-safe way for monitors to emit StartWatch/CancelWatch from background threads.
        Listener will pick these up and process them exactly like from handle().
        """
        with self.lock:
            pending = getattr(self, "_pending_actions", None)
            if pending is None:
                pending = self._pending_actions = []
            pending.append(action)

    #----- Logging methods -----#
    def set_logfile(self, path: str):
        """Set the logfile path at job start. Creates directory if needed."""
        self._logfile_path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.log("=== JOB LOG STARTED ===", console=False)

    def log(self, message: str, *, console: bool = False, color: str = ''):
        """
        Thread-safe logging.
        - Always appends to in-memory self.logs
        - Buffers for efficient disk writes
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

        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        line = f"[{timestamp}] {caller_tag}: {message}"

        self.logs.append(line)

        # Buffer for disk
        with self._log_lock:
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
            print(f"[LOG ERROR] Failed to write to {self._logfile_path}: {e}")

    def flush_logs(self):
        """Force flush remaining buffer — call at job end or cleanup"""
        with self._log_lock:
            self._flush_buffer()
        self.log("=== JOB LOG ENDED ===", console=False)