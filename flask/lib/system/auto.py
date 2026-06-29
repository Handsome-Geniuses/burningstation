import threading
import time
from typing import Callable

from lib.gpio import mdm
from lib.meter.meter_manager import METERMANAGER as mm
from lib.sse.question import ask_clients, setResponse
from lib.sse.sse_queue_manager import SSEQM
from lib.store.store import store
from lib.system import station
from lib.system.bay_guess import BAY_GUESS_BAY_STARTS
from lib.system.belt_logic import BAY_STARTS, sensors_to_boxes
from lib.system.states import states
from lib.utils import secrets


RETRY_INTERVAL_S = 2.0
NOTIFY_INTERVAL_S = 30.0
MOVE_CONFIRM_TIMEOUT_S = 45.0


class AutoCoordinator:
    def __init__(self):
        self._movement_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: set[tuple[str, str]] = set()

    def on_passive_done(self, meter_ip: str):
        self._enqueue("passive_done", meter_ip, self._bay0_to_bay1_then_physical)

    def on_physical_done(self, meter_ip: str):
        self._enqueue("physical_done", meter_ip, self._bay1_to_bay2)

    def _enqueue(self, action: str, meter_ip: str, target: Callable[[str], None]):
        key = (action, meter_ip)
        with self._pending_lock:
            if key in self._pending:
                return
            self._pending.add(key)
        self._notify(f"Auto queued {action} for {meter_ip}")

        def run():
            try:
                target(meter_ip)
            finally:
                with self._pending_lock:
                    self._pending.discard(key)

        threading.Thread(target=run, daemon=True, name=f"auto:{action}:{meter_ip}").start()

    def _flow_active(self, meter_ip: str) -> bool:
        if states.get("mode") != "auto":
            return False
        if states.get("emergency"):
            return False
        return meter_ip in mm.meters

    def _notify(self, msg: str, ntype: str = "info"):
        SSEQM.broadcast("notify", {"ntype": ntype, "msg": msg})

    def _wait_for_precheck(self, meter_ip: str, bay_name: str, precheck: Callable[[], object]) -> bool:
        last_notify = 0.0
        while self._flow_active(meter_ip):
            result = precheck()
            if result is None:
                return True

            now = time.time()
            if now - last_notify >= NOTIFY_INTERVAL_S:
                reason = result[0] if isinstance(result, tuple) else result
                self._notify(f"Auto waiting for {bay_name}: {reason}")
                last_notify = now

            time.sleep(RETRY_INTERVAL_S)

        self._notify(f"Auto paused for {meter_ip}; no longer active", "warn")
        return False

    def _start_station_load(self, move_type: str, **kwargs) -> bool:
        if secrets.MOCK:
            from lib.system import sim
            result = sim.mock_station_load(type=move_type, **kwargs)
        else:
            result = station.on_load(type=move_type, **kwargs)

        if isinstance(result, tuple) and len(result) >= 2 and int(result[1]) >= 400:
            self._notify(f"Auto station move {move_type} rejected: {result[0]}", "warn")
            return False

        return True

    def _bay_mds_full(self, bay_index: int) -> bool:
        start = bay_index * 3
        return all(states.get("mds", [False] * 9)[start:start + 3])

    def _bay_guess_exact(self, meter_ip: str, bay_index: int) -> bool:
        start = BAY_GUESS_BAY_STARTS[bay_index]
        return all(slot == meter_ip for slot in states.get("bayGuess", [None] * 15)[start:start + 3])

    def _bay_guess_at_left(self, meter_ip: str, left: int) -> bool:
        bay_guess = states.get("bayGuess", [None] * 15)
        return all(slot == meter_ip for slot in bay_guess[left:left + 3])

    def _wait_for_bay(self, meter_ip: str, bay_index: int) -> bool:
        deadline = time.time() + MOVE_CONFIRM_TIMEOUT_S
        while self._flow_active(meter_ip):
            if self._bay_guess_exact(meter_ip, bay_index) or self._bay_mds_full(bay_index):
                return True
            if time.time() >= deadline:
                self._notify(f"Auto move timed out waiting for bay{bay_index}", "error")
                return False
            time.sleep(0.25)
        return False

    def _move_to_bay(self, meter_ip: str, move_type: str, bay_index: int, precheck: Callable[[], object]) -> bool:
        if not self._flow_active(meter_ip):
            self._notify(f"Auto paused for {meter_ip}; no longer active", "warn")
            return False

        while self._flow_active(meter_ip):
            if not self._wait_for_precheck(meter_ip, f"bay{bay_index}", precheck):
                return False

            with self._movement_lock:
                if not self._flow_active(meter_ip):
                    self._notify(f"Auto paused for {meter_ip}; no longer active", "warn")
                    return False
                if precheck() is not None:
                    continue

                self._notify(f"Auto moving {meter_ip} to bay{bay_index}")
                if self._start_station_load(move_type):
                    confirmed = self._wait_for_bay(meter_ip, bay_index)
                    if confirmed:
                        self._notify(f"Auto confirmed {meter_ip} in bay{bay_index}")
                    return confirmed

            time.sleep(RETRY_INTERVAL_S)

        return False

    def _wait_for_unload_target(self, meter_ip: str, steps: int) -> bool:
        target_track = BAY_STARTS[2] + steps
        target_guess_left = BAY_GUESS_BAY_STARTS[2] + steps
        deadline = time.time() + MOVE_CONFIRM_TIMEOUT_S

        while self._flow_active(meter_ip):
            if (
                target_track in sensors_to_boxes(states.get("mds", [False] * 9))
                or self._bay_guess_at_left(meter_ip, target_guess_left)
            ):
                return True
            if time.time() >= deadline:
                self._notify(f"Auto unload timed out waiting for bay2{'_' * steps}", "error")
                return False
            time.sleep(0.25)

        return False

    def _auto_unload_steps(self) -> int:
        return max(0, min(2, int(store.settings.other.auto_unload_r)))

    def _move_to_unload_offset(self, meter_ip: str) -> bool:
        steps = self._auto_unload_steps()
        if steps <= 0:
            return True

        bay_label = f"bay2{'_' * steps}"
        precheck = lambda: station.load_R_unload_precheck(steps=steps)

        while self._flow_active(meter_ip):
            if not self._wait_for_precheck(meter_ip, bay_label, precheck):
                return False

            with self._movement_lock:
                if not self._flow_active(meter_ip):
                    self._notify(f"Auto paused for {meter_ip}; no longer active", "warn")
                    return False
                if precheck() is not None:
                    continue

                self._notify(f"Auto moving {meter_ip} to {bay_label}")
                if self._start_station_load("RU", steps=steps):
                    confirmed = self._wait_for_unload_target(meter_ip, steps)
                    if confirmed:
                        self._notify(f"Auto confirmed {meter_ip} in {bay_label}")
                    return confirmed

            time.sleep(RETRY_INTERVAL_S)

        return False

    def _move_to_bay2(self, meter_ip: str) -> bool:
        if not self._move_to_bay(meter_ip, "R", 2, station.load_R_precheck):
            return False
        return self._move_to_unload_offset(meter_ip)

    def _ready_meter_ips(self, preferred_ip: str) -> list[str]:
        ready_ips = [
            ip
            for ip, meter in mm.meters.items()
            if getattr(meter, "status", None) == "ready"
        ]
        if preferred_ip in ready_ips:
            return [preferred_ip, *[ip for ip in ready_ips if ip != preferred_ip]]
        return ready_ips

    def _ask_single_physical_confirmation(self, flow_meter_ip: str, candidate_ip: str) -> bool:
        try:
            meter = mm.get_meter(candidate_ip)
        except KeyError:
            return False

        meter.blink_until_start(max_duration=300)
        SSEQM.broadcast("status", {"ip": candidate_ip, "status": meter.status, "current_action": "blinking"})

        result_holder: dict[str, bool | None] = {"value": None}
        done = threading.Event()

        def ask():
            result_holder["value"] = ask_clients(
                title="Auto Physical",
                msg="Is the blinking meter in the middle?",
                id=f"auto-physical-{candidate_ip}",
                qtype="boolean",
                confirm="Yes",
                cancel="No",
            )
            done.set()

        threading.Thread(target=ask, daemon=True, name=f"auto:question:{candidate_ip}").start()

        while not done.wait(0.5):
            if not self._flow_active(flow_meter_ip) or candidate_ip not in mm.meters:
                setResponse(False)
                done.wait(2.0)
                break

        meter.blink_until_stop()
        SSEQM.broadcast("status", {"ip": candidate_ip, "status": meter.status, "current_action": ""})
        return result_holder["value"] is True

    def _ask_physical_confirmation(self, meter_ip: str) -> str | None:
        candidate_ips = self._ready_meter_ips(meter_ip)
        if not candidate_ips:
            self._notify("Auto physical paused; no ready meters to confirm", "warn")
            return None

        for index, candidate_ip in enumerate(candidate_ips):
            if not self._flow_active(meter_ip):
                return None
            if candidate_ip not in mm.meters:
                continue
            if getattr(mm.meters[candidate_ip], "status", None) != "ready":
                continue

            if index > 0:
                self._notify(f"Auto physical trying next ready meter: {candidate_ip}")

            if self._ask_single_physical_confirmation(meter_ip, candidate_ip):
                return candidate_ip

        return None

    def _bay0_to_bay1_then_physical(self, meter_ip: str):
        if not self._move_to_bay(meter_ip, "M", 1, station.load_M_precheck):
            return

        physical_meter_ip = self._ask_physical_confirmation(meter_ip)
        if not physical_meter_ip:
            self._notify(f"Auto physical skipped for {meter_ip}; moving to bay2", "warn")
            self._move_to_bay2(meter_ip)
            return

        if physical_meter_ip != meter_ip:
            self._notify(f"Auto physical confirmed {physical_meter_ip} instead of {meter_ip}", "warn")

        from lib.automation.jobs import start_physical_job

        success, msg = start_physical_job(physical_meter_ip)
        if not success:
            self._notify(f"Auto physical failed to start for {physical_meter_ip}: {msg}", "error")

    def _bay1_to_bay2(self, meter_ip: str):
        self._move_to_bay2(meter_ip)


AUTO_COORDINATOR = AutoCoordinator()
