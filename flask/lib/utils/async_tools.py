import threading
import time
from typing import Callable, Optional, Tuple

class AsyncManager:
    """
    Encapsulates an async operation with:
    - Pre-checks (to validate operation can run)
    - Timeout
    - Emergency stop
    - Automatic stopping of loops (time.sleep) inside the function
    - Callbacks: on_start, on_done, on_timeout, on_exception
      (defaults in decorator, overridable per call)
    """

    def __init__(self, name: str = "resource"):
        self.name = name
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._emergency = threading.Event()

    # -----------------------------
    # Emergency / reset
    # -----------------------------
    def emergency_stop(self):
        """Trigger emergency stop: prevents new operations and stops running ones."""
        with self._lock:
            self._emergency.set()
            self._running.clear()
        print(f"🚨 {self.name} emergency stop activated!")

    def emergency_reset(self):
        """Reset emergency stop: allows new operations to start."""
        with self._lock:
            self._emergency.clear()
            self._running.clear()
        print(f"✅ {self.name} emergency stop cleared!")

    # -----------------------------
    # Decorator for async operations
    # -----------------------------
    def operation(
        self,
        timeout: Optional[float] = None,
        precheck: Optional[Callable[..., Optional[Tuple[str,int]]]] = None,
        on_start: Optional[Callable[[], None]] = None,
        on_done: Optional[Callable[[bool], None]] = None,
        on_timeout: Optional[Callable[[], None]] = None,
        on_exception: Optional[Callable[[Exception], None]] = None,
    ):
        """
        Decorator for async operations:
        - Can define default callbacks in decorator arguments
        - Call-time kwargs can override these defaults
        """
        def decorator(fn):
            def wrapper(**kwargs):
                # -----------------------------
                # Extract callbacks from kwargs or use defaults
                # -----------------------------
                start_cb = kwargs.pop('on_start', on_start or (lambda: print(f"[{fn.__name__}] started")))
                done_cb = kwargs.pop('on_done', on_done or (lambda stopped=False: print(f"[{fn.__name__}] completed")))
                timeout_cb = kwargs.pop('on_timeout', on_timeout or (lambda: print(f"[{fn.__name__}] timed out")))
                exception_cb = kwargs.pop('on_exception', on_exception or (lambda e: print(f"[{fn.__name__}] Exception: {e}")))

                # -----------------------------
                # Busy / emergency check before starting
                # -----------------------------
                with self._lock:
                    if self._emergency.is_set():
                        print(f"[{self.name}] Cannot start {fn.__name__} — emergency stop active!")
                        return "Emergency stop active", 500
                    if self._running.is_set():
                        print(f"[{self.name}] Cannot start {fn.__name__} — resource busy.")
                        return "Already running", 409

                    # Pre-check
                    if precheck:
                        check_result = precheck(**kwargs)
                        if check_result is not None:
                            return check_result

                    self._running.set()
                    print(f"[{self.name}] Starting {fn.__name__}...", flush=True)
                    start_cb()  # 🔹 Call on_start

                # Default return value (can be updated by thread)
                result = {"status": ("Operation started", 202)}

                # -----------------------------
                # Threaded operation with emergency/timeout support
                # -----------------------------
                def run_operation():
                    try:
                        # Patch time.sleep to check emergency every 50ms
                        original_sleep = time.sleep

                        def emergency_sleep(duration):
                            interval = 0.05
                            elapsed = 0
                            while elapsed < duration:
                                if self._emergency.is_set():
                                    raise RuntimeError("Stopped by emergency/timeout")
                                original_sleep(min(interval, duration - elapsed))
                                elapsed += interval

                        time.sleep = emergency_sleep  # override sleep

                        # Run the actual function normally
                        fn(**kwargs)
                        result["status"] = ("Operation completed", 200)

                    except RuntimeError as e:
                        result["status"] = ("Stopped by emergency/timeout", 499)
                        print(f"[{fn.__name__}] {e}")

                    except Exception as e:
                        result["status"] = (f"Error: {e}", 500)
                        exception_cb(e)  # 🔹 Call exception callback

                    finally:
                        # Restore original sleep and mark operation finished
                        time.sleep = original_sleep
                        self._running.clear()
                        done_cb(stopped=self._emergency.is_set())

                thread = threading.Thread(target=run_operation, daemon=True)
                thread.start()

                # -----------------------------
                # Timeout watcher
                # -----------------------------
                if timeout is not None:
                    def watch():
                        thread.join(timeout=timeout)
                        if thread.is_alive() and not self._emergency.is_set():
                            print(f"[{fn.__name__}] Operation timed out")
                            self._emergency.set()
                            timeout_cb()
                            result["status"] = ("Timeout", 408)

                    threading.Thread(target=watch, daemon=True).start()

                return result["status"]

            return wrapper
        return decorator





def async_fire_and_forget(fn: Callable):
    """
    Runs a function in a background thread immediately.
    No return value, no stacking control, just fire-and-forget.
    """
    def wrapper(*args, **kwargs):
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()
    return wrapper



