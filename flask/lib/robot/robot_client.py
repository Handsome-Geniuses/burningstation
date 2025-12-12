import socket
import json
import time
import threading
import logging
from collections import deque
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)


class RobotClient:
    """
    Thread-safe, persistent TCP client for the Jaka Zu 7 robot controller.
    Designed for use on the burningpi/station to control and monitor the robot.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, host='192.168.8.181', port=42000, heartbeat_interval=60):
        if hasattr(self, "_initialized"):
            return
        
        self.host = host
        self.port = port
        self.sock = None
        self._main_lock = threading.RLock()
        self._request_id = 0
        self._pending_responses = {}  # id -> dict with event, data, error
        self._event_queue = deque(maxlen=15)  # Stores last 15 events
        self._reader_thread = None
        self._heartbeat_thread = None
        self._heartbeat_interval = heartbeat_interval
        self._running = False

        self.connect()
        self._initialized = True
        log.info("RobotClient singleton created and connected")

    def connect(self):
        with self._main_lock:
            if self.sock:
                self.close()

            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((self.host, self.port))
                self.sock.settimeout(None)
                self._running = True

                self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
                self._reader_thread.start()

                if self._heartbeat_interval > 0:
                    self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
                    self._heartbeat_thread.start()

                log.info("Connected to robot at %s:%s", self.host, self.port)
            except Exception as e:
                raise RuntimeError(f"Failed to connect to robot: {e}")

    def close(self):
        with self._main_lock:
            self._running = False
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                self.sock.close()
                self.sock = None
            log.info("Robot connection closed")

    def _get_next_id(self):
        with self._main_lock:
            self._request_id += 1
            return self._request_id

    def _send_json(self, msg):
        with self._main_lock:
            if not self.sock:
                raise RuntimeError("Not connected")
            try:
                wire = (json.dumps(msg) + "\n").encode("utf-8")
                self.sock.sendall(wire)
            except Exception as e:
                log.error("Send failed: %s", e)
                self.close()
                raise RuntimeError(f"Send failed: {e}")

    def _read_loop(self):
        buf = ""
        try:
            while self._running:
                try:
                    data = self.sock.recv(4096).decode("utf-8")
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning("Bad JSON received: %r", line)
                        continue
                    self._process_message(msg)
        finally:
            self.close()

    def _process_message(self, msg):
        msg_type = msg.get("type")

        if msg_type == "response":
            req_id = msg.get("id")
            with self._main_lock:
                if req_id in self._pending_responses:
                    placeholder = self._pending_responses.pop(req_id)
                    if msg.get("status") == "success":
                        placeholder["data"] = msg.get("data", {})
                    else:
                        placeholder["error"] = msg.get("error", "Unknown error")
                    placeholder["event"].set()

        elif msg_type == "event":
            event_name = msg.get("event")
            job_id = msg.get("job_id")
            log.info("EVENT → %s (job_id=%s)", event_name, job_id)
            with self._main_lock:
                self._event_queue.append(msg)

    def _heartbeat_loop(self):
        while self._running:
            time.sleep(self._heartbeat_interval)
            if not self._running:
                break
            try:
                self.send_command("ping", timeout=5)
            except Exception as e:
                log.warning("Heartbeat failed (connection likely dead): %s", e)
                break

    def send_command(self, command: str, params=None, timeout=3.0):
        """Send a quick command and wait for response."""
        if params is None:
            params = {}
        req_id = self._get_next_id()
        msg = {"command": command, "params": params, "id": req_id}

        event = threading.Event()
        placeholder = {"event": event, "data": None, "error": None}

        with self._main_lock:
            self._pending_responses[req_id] = placeholder

        log.debug("SENT → %s", msg)
        self._send_json(msg)

        if not event.wait(timeout):
            with self._main_lock:
                self._pending_responses.pop(req_id, None)
            raise TimeoutError(f"Timeout waiting for response to command: {command}")

        if placeholder["error"]:
            raise RuntimeError(f"Command '{command}' failed: {placeholder['error']}")
        return placeholder["data"]

    def run_program(self, name: str, args=None, timeout=3.0):
        """Send run_program and return job_id if accepted."""
        if args is None:
            args = {}
        result = self.send_command("run_program", {"name": name, "args": args}, timeout=timeout)
        job_id = result.get("job_id")
        log.info("Program '%s' started with job_id = %s", name, job_id)
        return job_id

    def wait_for_event(self, event_name: str, job_id: Optional[str] = None, timeout: float = 30.0):
        """Wait up to `timeout` seconds for a specific event. Consumes the first match."""
        log.info("waiting for event '%s'%s with timeout=%s sec", event_name, f" on job {job_id}" if job_id else "", timeout)
        start = time.time()

        while time.time() - start < timeout:
            with self._main_lock:
                if not self.sock:
                    raise RuntimeError(f"Connection dropped while waiting for event: {event_name}")
                
                for msg in list(self._event_queue):
                    if msg.get("event") == event_name:
                        if job_id is None or msg.get("job_id") == job_id:    
                            self._event_queue.remove(msg)
                            print(f"Removed and returning msg: {msg}")
                            return msg.get("data", {})
            
            time.sleep(0.05)
        
        raise TimeoutError(f"Timeout waiting for event: {event_name}")

    def get_recent_events(self):
        """Return list of recently received events (latest first)."""
        with self._main_lock:
            return list(self._event_queue)

    def try_get_event(
        self,
        event_name: str,
        job_id: Optional[str] = None,
        consume: bool = True
    ) -> tuple[bool, dict]:
        """
        Non-blocking check for an event.

        Returns:
            (found: bool, data: dict)
                - found = True  → event was in queue
                - found = False → event not present
                - data = msg["data"] if found, else {}

        If consume=True (default), removes the event from queue when found.
        If consume=False, leaves it in queue (peek only).
        """
        with self._main_lock:
            for msg in list(self._event_queue):
                if msg.get("event") == event_name:
                    if job_id is None or msg.get("job_id") == job_id:
                        data = msg.get("data", {})
                        if consume:
                            self._event_queue.remove(msg)
                        return True, data
            # Not found
            return False, {}

    def wait_until_ready(self, wait_timeout: float):
        """Wait up to 'timeout' seconds for the robot to be ready (NOT busy)."""
        log.info("waiting for robot ready with timeout=%s sec", wait_timeout)
        start = time.time()
        while time.time() - start < wait_timeout:
            status = self.send_command("get_system_status")
            if not status.get("robot_busy", True):
                return
            
            time.sleep(0.5)
        
        raise TimeoutError(f"Timeout waiting for robot to be ready")


if __name__ == "__main__":
    client = RobotClient()

    try:
        print("Robot status:", client.send_command("get_system_status", timeout=5))

        # job_id = client.run_program("run_move_home")
        # job_id = client.run_program("run_find_meter", args={"meter_type": "ms2.5"})

        # client.wait_for_event("program_started", job_id=job_id, timeout=10)
        # print("Program started!")

        # client.wait_for_event("program_done", job_id=job_id, timeout=30)
        # print("Program finished successfully!")

        # # print("\nRecent events:")
        # # for ev in client.get_recent_events():
        # #     print(f"  {ev['event']} | job_id={ev.get('job_id')} | data={ev.get('data')}")

        # print(client.send_command("get_system_status"))
        print(client.send_command("get_charuco_frame"))

    except Exception as e:
        print("Error:", e)
    finally:
        client.close()