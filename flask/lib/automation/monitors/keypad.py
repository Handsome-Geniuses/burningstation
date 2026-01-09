import re
from typing import Optional, Iterable, Set, Dict, List, Tuple

from lib.automation.monitors.models import (
    LogEvent, Action, StartWatch, CancelWatch, MarkSuccess, MetaUpdate,
    ProgressUpdate, BLUE, GREEN, YELLOW, RED, DIM, RESET
)
from lib.automation.shared_state import SharedState


KEY_LAYOUTS: Dict[str, List[str]] = {
    "1x6": ["help","up","down","cancel","accept","max"],
    "1x7": ["help","up","down","cancel","accept","max","center"],
    "6x7": [
        "0","1","2","3","4","5","6","7","8","9",
        "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",
        "ASTERISK","POUND","BACK","ENTER"
    ],
}


class KeypadMonitor:
    id = "keypad"

    @staticmethod
    def _layouts_for_meter(meter_type: str, firmwares: Dict[str, str]) -> List[str]:
        mt = (meter_type or "").lower()
        # Later (if needed) we can use firmware names to set layouts
        layouts = []
        if firmwares.get("KEY_PAD_2"):
            layouts.append("6x7")
        if mt == "ms2.5" and firmwares.get("KBD_CONTROLLER"):
            layouts.append("1x6")
        if mt == "ms3" and firmwares.get("KBD_CONTROLLER"):
            layouts.append("1x7")
        return layouts

    def __init__(self,
                 shared: SharedState,
                 inactivity_timeout_s: float = 15.0,
                 layouts: Optional[List[str]] = None,
                 count: int = 1,
                 verbose: bool = False,
                 meter_type: Optional[str] = None,
                 firmwares: Optional[Dict[str, str]] = None):
        self.shared = shared
        self.verbose = verbose
        self.timeout_s = float(inactivity_timeout_s)
        self.required_per_key = max(1, int(count))
        self._gap_key: Optional[str] = None
        if not layouts:
            layouts = self._layouts_for_meter(meter_type or "", firmwares or {})
        self.layouts: List[str] = list(layouts or [])

        self.layout_keys: Dict[str, Set[str]] = {
            name: {self._norm(k) for k in KEY_LAYOUTS.get(name, [])}
            for name in self.layouts
            if KEY_LAYOUTS.get(name)
        }

        exp: Set[str] = set()
        for keys in self.layout_keys.values():
            exp.update(keys)
        self.expected: Set[str] = exp

        self.layout_done: Set[str] = set()
        self.seen_counts: Dict[str, int] = {}
        self._re_line = re.compile(
            r'KEY_PRESSED:\s*(?P<key>[^,]+),\s*isAutoRepeat=(?P<ar>true|false),\s*from\s+(?P<src>\S+)',
            re.IGNORECASE
        )
        self._allowed_src = {"KEY_PAD_2", "KBD_CONTROLLER"}
        self._last_progress: Tuple[int,int] = (-1, -1)

        self.shared.log(f"[{self.id}] meter_type={meter_type}, layouts={self.layouts}")
        if not self.expected:
            self.shared.log(f"[{self.id}] No expected keys resolved from layouts; will only run gap timer", color=YELLOW)
            # Should add something to let test_keypad know to stop the test since there arent any keys to test

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

    def _arm_gap(self, ev: LogEvent, *, last: Optional[str] = None) -> Iterable[Action]:
        yield from self._cancel_gap()
        self._gap_key = f"{self.id}:gap:{int(ev.ts.timestamp())}"
        yield StartWatch(
            key=self._gap_key,
            timeout_s=self.timeout_s,
            device=self.id,
            on_timeout_msg=f"No keypad activity for {self.timeout_s:.0f}s"
        )

    def _progress_counts(self) -> Tuple[int,int]:
        total = len(self.expected) * self.required_per_key
        done = 0
        if total:
            rp = self.required_per_key
            done = sum(min(self.seen_counts.get(k, 0), rp) for k in self.expected)
        return done, total

    def _all_satisfied(self) -> bool:
        if not self.expected:
            return False
        rp = self.required_per_key
        return all(self.seen_counts.get(k, 0) >= rp for k in self.expected)

    def _layout_satisfied(self, layout: str) -> bool:
        keys = self.layout_keys.get(layout, set())
        if not keys:
            return False
        rp = self.required_per_key
        return all(self.seen_counts.get(k, 0) >= rp for k in keys)

    def _missing_summary(self) -> str:
        rp = self.required_per_key
        miss = [f"{k}({self.seen_counts.get(k,0)}/{rp})"
                for k in sorted(self.expected) if self.seen_counts.get(k,0) < rp]
        return ", ".join(miss[:8]) + (" …" if len(miss) > 8 else "")

    def handle(self, ev: LogEvent) -> Optional[Iterable[Action]]:
        msg = ev.msg
        self.shared.log(f"[{self.id}] Handle: {msg}", color=DIM)

        m = self._re_line.search(msg)
        if not m:
            return None

        key = self._norm(m.group("key"))
        src = self._norm(m.group("src"))
        if self._allowed_src and src not in self._allowed_src:
            self.shared.log(f"[{self.id}] ignore src={src}", color=DIM)
            return None

        actions: List[Action] = []

        actions.extend(self._arm_gap(ev, last=key))

        if self.expected and key not in self.expected:
            self.shared.log(f"[{self.id}] non-required key={key}; gap re-armed", color=DIM)
            return actions

        # Count this key
        c = self.seen_counts.get(key, 0) + 1
        self.seen_counts[key] = c
        current_cycle, total_cycles = self._progress_counts()
        actions.append(ProgressUpdate(self.id, current_cycle, total_cycles))
        self.shared.log(f"[{self.id}] {key} #{c}/{self.required_per_key}; missing={self._missing_summary()}", color=DIM)

        # Check each layout for “just completed”
        for layout, keys in self.layout_keys.items():
            if layout in self.layout_done:
                continue
            if keys and self._layout_satisfied(layout):
                self.layout_done.add(layout)
                actions.append(MetaUpdate(self.id, {"layouts_done": sorted(self.layout_done)}))
                total = len(keys)
                self.shared.log(f"[{self.id}] layout '{layout}' completed ({total} keys × {self.required_per_key})", color=GREEN)

        # Overall completion across all selected layouts
        if self._all_satisfied():
            self.shared.log(f"[{self.id}] all required keys reached {self.required_per_key} presses — success", color=GREEN)
            actions.extend(self._cancel_gap())
            actions.append(MarkSuccess(device=self.id, message="All required keypad presses observed"))


        return actions

