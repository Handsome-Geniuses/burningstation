"""Retry a complete subtest only after its workers have unwound and recovered.

Update ``lib/docs/meter/lifecycle.md`` and ``lib/docs/meter/supervisor.md`` when
changing retry budgets, cleanup/handoff, or the in-flight call-in exception.
"""
from copy import deepcopy
import time

from lib.automation.helpers import StopAutomation
from lib.meter.lifecycle import MeterInterrupted, RecoveryFailed, session_for


def stop_robot():
    """Request abort and require ready acknowledgement before allowing recovery UI."""
    from lib.robot.robot_client import RobotClient
    client = RobotClient()
    try:
        client.send_command("abort_program", timeout=3)
        client.wait_until_ready(30)
    except Exception as exc:
        raise RecoveryFailed(f"Robot did not acknowledge stopping: {exc}") from exc


def await_meter(meter, shared):
    """Wait for recovery and acknowledge its epoch; the caller must be quiescent."""
    session = session_for(meter)
    if session is not None:
        shared.attempt_epoch = session.wait_ready(shared)
        shared.disruption_event.clear()


def run_subtest(meter, shared, name, function, *, robot=False, prepare=None, max_restarts=2):
    """Return function() after a valid attempt, restarting only interrupted work.

    ``prepare(attempt)`` runs after recovery before each attempt; use it for a
    fresh physical pose/banner. ``robot=True`` requires abort/ready handoff on
    interruption. Snapshots roll back inferred failures but retain interrupted
    attempt metadata. A triggered call-in is never replayed. Exhaustion raises
    RecoveryFailed; cancellation propagates. Legacy meters call function directly.
    Retry metadata reuses a verified current-generation inventory when available.
    """
    session = session_for(meter)
    if session is None:
        return function()
    deadline = time.monotonic() + 900
    shared.meter_session = session
    session.shared = shared
    for attempt in range(max_restarts + 1):
        try:
            shared.attempt_epoch = session.wait_ready(shared, timeout=max(0, deadline - time.monotonic()))
        except RecoveryFailed as exc:
            shared.extras["meter_disruption"] = str(exc)
            raise
        shared.disruption_event.clear()
        shared.lifecycle_observer = False
        previous_results = deepcopy(shared.device_results)
        previous_meta = deepcopy(shared.device_meta)
        previous_error = shared.last_error
        completed = False
        try:
            shared.log(f"\n{'=' * 25} RUNNING SUBTEST {name.upper()} / ATTEMPT {attempt + 1} {'=' * 25}")
            if attempt:
                # Use SSHMeter's existing cache. Only an observed generation
                # change/explicit refresh clears it; retry never forces a walk.
                meter.get_info()
                shared.log(f"Meter recovered; restarting {name} (attempt {attempt + 1}/{max_restarts + 1})",
                           console=True)
            if prepare:
                prepare(attempt)
            result = function()
            completed = True
            if shared.abort_event.is_set():
                raise StopAutomation("Cancelled by operator")
            if name in {"call in", "call_in", "cycle_call_in"}:
                await_meter(meter, shared)
            session.checkpoint(shared.attempt_epoch)
            return result
        except Exception as exc:
            if shared.abort_event.is_set():
                if robot:
                    stop_robot()
                raise
            interrupted = (isinstance(exc, MeterInterrupted) or session.epoch != shared.attempt_epoch
                           or not session.ready or shared.disruption_event.is_set())
            if not interrupted:
                raise
            if completed and name in {"call in", "call_in", "cycle_call_in"}:
                # A second update racing the return must not replay a call-in
                # whose original transaction has already validated.
                await_meter(meter, shared)
                return result
            record = {"subtest": name, "attempt": attempt + 1, "reason": str(exc),
                      "epoch": session.epoch, "results": deepcopy(shared.device_results),
                      "metadata": deepcopy(shared.device_meta)}
            shared.extras.setdefault("meter_interruptions", []).append(record)
            shared.log(f"{name} attempt {attempt + 1} interrupted: {exc}; waiting for meter recovery", console=True)
            if robot:
                stop_robot()
            if isinstance(exc, RecoveryFailed) or attempt >= max_restarts or time.monotonic() >= deadline:
                shared.extras["meter_disruption"] = str(exc)
                for device, status in list(shared.device_results.items()):
                    if status in {"fail", "running"} and previous_results.get(device) != "fail":
                        shared.device_results[device] = "interrupted"
                raise RecoveryFailed(f"{name}: recovery/retry limit reached; {exc}", session.epoch) from exc
            if shared.extras.get("call_in_in_flight"):
                # An already-triggered transaction is never automatically sent
                # again. cycle_call_in owns its observation/validation phases.
                raise RecoveryFailed(f"In-flight call-in could not recover: {exc}", session.epoch) from exc
            shared.device_results.clear()
            shared.device_results.update(previous_results)
            shared.device_meta.clear()
            shared.device_meta.update(previous_meta)
            shared.last_error = previous_error
            # Only reset a local subtest failure caused by this disruption;
            # operator cancellation is checked again while holding the lock.
            with shared.lock:
                if shared.abort_event.is_set():
                    raise StopAutomation("Cancelled by operator")
                shared.stop_event.clear()
        finally:
            shared.lifecycle_observer = False
    raise RecoveryFailed(f"{name}: recovery limit reached")
