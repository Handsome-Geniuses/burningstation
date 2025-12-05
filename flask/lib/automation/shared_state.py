# shared_state.py
import threading
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
        self.db_data = {}

    def set_allowed(self, devices: set[str], reason: str = ""):
        self.allowed_monitors = devices
        # print(f"[SharedState] allowed_monitors set to {devices} {('- ' + reason) if reason else ''}")

    def broadcast_progress(self, ip: str, program: str, current_cycle: int, total_cycles: int):
        """Broadcast progress updates during test cycles."""
        SSEQM.broadcast("progress", {
            "ip": ip,
            "program": program,
            "current_cycle": current_cycle,
            "total_cycles": total_cycles
        })
