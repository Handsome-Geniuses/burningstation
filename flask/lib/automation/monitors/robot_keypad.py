import re
import threading
import time
from typing import Iterable, List, Optional, Dict

from lib.automation.monitors.models import (
    LogEvent, Action, StartWatch, CancelWatch, MarkSuccess, ProgressUpdate,
    RED, GREEN, YELLOW, DIM, RESET
)
from lib.robot.robot_client import RobotClient


class RobotKeypadMonitor:
    """
    Robot-driven keypad monitor.
    - Watches real KEY_PRESSED logs and counts presses
    - Uses robot events ("button_press") to arm/disarm per-button failure timers
    - Fails fast if robot starts pressing a button but never completes it
    """
    id = "robot_keypad"

    def __init__(
        self,
        buttons: List[str],
        shared = None,
        count: int = 1,
        inactivity_timeout_s: float = 30.0,
        per_button_timeout_s: float = 20.0,   # how long to wait between robot pressing event and meter log confirmation
        verbose: bool = False,
        **kwargs
    ):
        self.shared = shared
        self.verbose = verbose
        self.inactivity_timeout_s = float(inactivity_timeout_s)
        self.per_button_timeout_s = float(per_button_timeout_s)
        self.required_per_key = max(1, int(count))
        self.ignore_repeats = kwargs.get("ignore_reapeats", True)

        # Normalize expected buttons
        self.expected = {self._norm(b) for b in buttons if b.strip()}
        if not self.expected:
            raise ValueError("At least one button must be provided")

        self.seen_counts: Dict[str, int] = {k: 0 for k in self.expected}
        self._gap_key: Optional[str] = None

        # Per-button failure watchdogs (armed when robot says "pressing", cancelled on success/fail)
        self._button_watches: Dict[str, str] = {}   # button_name → watch_key

        self._re_line = re.compile(
            r'KEY_PRESSED:\s*(?P<key>[^,]+),\s*isAutoRepeat=(?P<ar>true|false),\s*from\s+(?P<src>\S+)',
            re.IGNORECASE
        )
        self._allowed_src = {"KEY_PAD_2", "KBD_CONTROLLER"}

        if self.verbose:
            print(f"[robot_keypad] Expecting {len(self.expected)} buttons × {self.required_per_key}")

        self.robot = RobotClient()

        # Background thread: watches robot events
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ #
    # Background thread — polls robot events
    # ------------------------------------------------------------------ #
    def _run(self):
        if self.verbose:
            print(f"{GREEN}[robot_keypad] background thread started{RESET}")
        
        # All past events get cleared when calling jobs.py.start_physical_job so there shouldnt be any old 'button_press' events
        while not self._stop_event.is_set():
            if self.shared and (
                self.shared.stop_event.is_set() or
                getattr(self.shared, "end_listener", None) and self.shared.end_listener.is_set()
            ):
                break

            self._check_robot_events()
            if self._stop_event.wait(0.3):
                break

        if self.verbose:
            print(f"{YELLOW}[robot_keypad] background thread exited{RESET}")

    def _check_robot_events(self) -> None:
        """Poll robot events and queue actions according to strict rules."""
        while True:
            found, data = self.robot.try_get_event("button_press", consume=True)
            if not found:
                break

            button_name_raw = data.get("button_name", "")
            button_name = self._norm(button_name_raw)
            if button_name not in self.expected:
                if self.verbose:
                    print(f"{DIM}[robot_keypad] ignoring unexpected button: {button_name_raw}{RESET}")
                continue

            action_type = data.get("action")
            pressed = data.get("pressed", None)  # only present when action=="pressed"

            if action_type == "pressing":
                if self.verbose:
                    print(f"{YELLOW}[robot_keypad] robot STARTED pressing '{button_name_raw}' → arming timeout{RESET}")

                # Cancel any previous dangling watch (shouldn't happen, but be safe)
                for cancel in self._cancel_button_watch(button_name):
                    if self.shared:
                        self.shared.queue_action(cancel)

                # ARM NEW TIMER
                watch_key = f"{self.id}:button:{button_name}:{int(time.time() * 1000)}"
                self._button_watches[button_name] = watch_key

                timer = StartWatch(
                    key=watch_key,
                    timeout_s=self.per_button_timeout_s,
                    device=self.id,
                    on_timeout_msg=f"Robot pressing '{button_name_raw}' but the meter did not see this button pressed in the logs within {self.per_button_timeout_s}s",
                    severity="critical"
                )
                if self.shared:
                    self.shared.queue_action(timer)

            elif action_type == "pressed":
                if pressed is False:
                    # ROBOT TRIED BUT FAILED → cancel timer (prevents false timeout if meter never logs it)
                    if self.verbose:
                        print(f"{RED}[robot_keypad] robot reports FAILED press on '{button_name_raw}' → cancelling timer{RESET}")

                    for cancel in self._cancel_button_watch(button_name):
                        if self.shared:
                            self.shared.queue_action(cancel)

                elif pressed is True:
                    # We expect the meter to log KEY_PRESSED → handle() will cancel the timer
                    if self.verbose:
                        print(f"{GREEN}[robot_keypad] robot reports SUCCESS on '{button_name_raw}' — waiting for meter log...{RESET}")
    
    def _cancel_button_watch(self, button_name: str) -> List[Action]:
        watch_key = self._button_watches.pop(button_name, None)
        if watch_key:
            if self.verbose:
                print(f"{GREEN}[robot_keypad] CANCELLED timeout for {button_name}{RESET}")
            return [CancelWatch(watch_key)]
        return []
    
    # ------------------------------------------------------------------ #
    # Log handling — real key presses from meter
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norm(s: str) -> str:
        return (s or "").strip().upper()

    def interested(self, msg: str) -> bool:
        return "key_pressed:" in msg.lower()

    def _cancel_gap(self) -> Iterable[Action]:
        if self._gap_key:
            k = self._gap_key
            self._gap_key = None
            yield CancelWatch(k)

    def _arm_gap(self, ev: LogEvent) -> Iterable[Action]:
        yield from self._cancel_gap()
        self._gap_key = f"{self.id}:gap:{int(ev.ts.timestamp())}"
        yield StartWatch(
            key=self._gap_key,
            timeout_s=self.inactivity_timeout_s,
            device=self.id,
            on_timeout_msg=f"No keypad activity for {self.inactivity_timeout_s:.0f}s"
        )

    def _is_complete(self) -> bool:
        return all(self.seen_counts.get(k, 0) >= self.required_per_key for k in self.expected)

    def handle(self, ev: LogEvent) -> Optional[Iterable[Action]]:
        if not (m := self._re_line.search(ev.msg)):
            return None
        
        if self.ignore_repeats and m.group("ar").lower() == "true":
            print(f"[{self.id}] ignoring auto-repeat for key {m.group('key')}")
            if self.verbose:
                print(f"[{self.id}] ignoring auto-repeat for key {m.group('key')}")
            return None
    
        key = self._norm(m.group("key"))
        src = self._norm(m.group("src"))
        if src not in self._allowed_src:
            return None

        actions: List[Action] = []
        actions.extend(self._arm_gap(ev))  # re-arm global inactivity timer

        if key not in self.expected:
            return actions  # ignore unexpected keys

        # Valid real key press detected!
        self.seen_counts[key] += 1
        if self.verbose:
            print(f"{GREEN}[{self.id}] '{key}' pressed -> {self.seen_counts[key]}/{self.required_per_key}{RESET}")

        # Cancel any pending per-button failure watchdog for this key
        if key in self._button_watches:
            if self.verbose:
                print(f"{GREEN}[{self.id}] meter confirmed press -> cancelling robot timeout for '{key}'{RESET}")
            actions.extend(self._cancel_button_watch(key))

        # Check for completion
        if self._is_complete():
            actions.extend(self._cancel_gap())
            actions.append(MarkSuccess(device=self.id, message="All keys successfully pressed by robot"))

        return actions
