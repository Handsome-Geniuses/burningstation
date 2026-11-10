"""Session state shared by discovery, controls, and test attempts.

This module deliberately has no hardware, SSH, or automation imports. All waits
use a monotonic clock; an MS3 generation and a disruption are different things
(sleep, for example, need not change the process).

When changing readiness, ownership, or phase semantics, update
``lib/docs/meter/lifecycle.md`` and ``lib/docs/meter/supervisor.md`` too.
"""
from contextlib import contextmanager
from copy import deepcopy
import threading
import time
from uuid import uuid4


class MeterInterrupted(RuntimeError):
    """An attempt lost its meter context; reason/epoch describe the disruption."""
    def __init__(self, reason, epoch=None):
        self.reason = reason
        self.epoch = epoch
        super().__init__(f"Meter interrupted: {reason}")


class RecoveryFailed(MeterInterrupted):
    """The attempt must not be converted to a peripheral failure or retried."""


def session_for(meter):
    """Read the session attribute already attached to this Python meter object.

    This performs no network I/O, page read, locking, or wait. Legacy/mock
    objects without an attached session return None and use their original path.
    """
    # Avoid manufacturing sessions on legacy fakes and unittest.mock objects.
    return vars(meter).get("session")


class MeterSession:
    """One identified meter's lifetime, independent of individual jobs or reboots.

    ``ready`` means the app is safe for admission/recovery; public readiness also
    requires ``admitted`` (complete inventory/DB initialization) and journal catchup.
    ``epoch`` invalidates in-flight work even if recovery finishes before a worker
    notices. The condition protects transitions; thread-local bindings authorize
    reentrant controls without letting unrelated request threads borrow a job.
    """
    def __init__(self, meter, *, recovery_timeout=300.0):
        self.meter = meter
        self.id = uuid4().hex
        self.condition = threading.Condition(threading.RLock())
        self.local = threading.local()
        self.owner = None
        self.shared = None
        self.recovery_allowed = False
        self.epoch = 0
        self.phase = "initializing"
        self.sleep_pending = False
        self.reason = "Waiting for MS3 and diagnostics"
        self.last_interruption = None
        self.generation = None
        self.identity_mismatch = False
        self.ready = False
        self.admitted = False
        self.recovery_since = time.monotonic()
        self.recovery_timeout = recovery_timeout
        self.link = "unknown"
        self.ui = "unknown"
        self.journal_connected = False
        self.info = {}
        self.initialization_step = "Waiting to read meter information"
        self.runtime_sec = None
        self.startup_remaining_s = None
        self.stable_remaining_s = None
        self.desired = {"mode": "stock", "banner": "", "results": None, "brightness": None}
        self.display_revision = 0
        self.display_applied = None
        self.subscribers = set()
        self.stopped = threading.Event()
        self.supervisor = None

    def snapshot(self):
        """Return cached, JSON-safe UI state without performing meter I/O.

        Countdown values are minimum settling waits, not a guaranteed ready ETA;
        diagnostics, client idle, inventory, and journal catchup may take longer.
        """
        with self.condition:
            can_start = self.ready and self.admitted and (self.supervisor is None or self.journal_connected)
            phase = "initializing" if self.ready and not self.admitted else self.phase
            reason = self.initialization_step if self.ready and not self.admitted else self.reason
            if self.ready and self.admitted and not can_start:
                phase, reason = "observing", "Reconnecting continuous journal capture"
            return {"session_id": self.id, "phase": phase, "reason": reason,
                    "ready": can_start, "epoch": self.epoch, "link": self.link,
                    "ui": self.ui, "journal_connected": self.journal_connected,
                    "generation": self.generation, "owner": self.owner,
                    "last_interruption": self.last_interruption,
                    "runtime_sec": self.runtime_sec, "startup_remaining_s": self.startup_remaining_s,
                    "stable_remaining_s": self.stable_remaining_s,
                    "initialization_step": self.initialization_step if not self.admitted else None,
                    "log_path": self.supervisor.log_path if self.supervisor else None}

    def describe(self, phase, reason):
        """Refine a waiting phase without inventing another interruption/epoch."""
        with self.condition:
            if not self.ready and not self.stopped.is_set():
                self.phase, self.reason = phase, reason
                self.condition.notify_all()

    def initializing(self, step):
        """Expose admission progress while external job starts remain gated."""
        with self.condition:
            self.initialization_step = step
        if self.supervisor:
            self.supervisor._log("initialization", step=step)

    def interrupt(self, reason, *, phase="recovering", new_generation=False):
        """Latch loss of readiness and notify workers; repeated samples share a deadline."""
        with self.condition:
            if self.ready or new_generation or (phase != self.phase and phase in {"updating", "sleep", "restarting"}):
                self.epoch += 1
                self.last_interruption = reason
            if self.ready:
                self.recovery_since = time.monotonic()
            self.ready = False
            if phase == "sleep":
                self.sleep_pending = True
            self.phase, self.reason = phase, reason
            if self.shared is not None:
                self.shared.disruption_event.set()
            self.condition.notify_all()

    def mark_ready(self):
        """Mark the observed app ready; admission and journal gates still apply."""
        with self.condition:
            if self.stopped.is_set():
                return
            self.ready = True
            self.sleep_pending = False
            self.startup_remaining_s = self.stable_remaining_s = None
            self.phase, self.reason = "ready", ""
            self.condition.notify_all()

    def claim(self, owner):
        """Atomically reserve an admitted, observed meter; return False if unavailable."""
        with self.condition:
            if self.stopped.is_set() or self.owner is not None or not self.ready or not self.admitted:
                return False
            if self.supervisor is not None and not self.journal_connected:
                return False
            self.owner = owner
            return True

    def release(self, owner):
        """Release only the matching lease, after worker/result cleanup is finished."""
        with self.condition:
            if self.owner == owner:
                self.owner = None
                self.shared = None
                self.recovery_allowed = False
                self.condition.notify_all()

    @contextmanager
    def bind(self, owner=None, *, maintenance=False):
        """Authorize this thread temporarily; maintenance also pins the recovery epoch."""
        previous = (getattr(self.local, "owner", None), getattr(self.local, "maintenance", False),
                    getattr(self.local, "maintenance_epoch", None))
        self.local.owner, self.local.maintenance = owner, maintenance
        self.local.maintenance_epoch = self.epoch if maintenance else None
        try:
            yield
        finally:
            self.local.owner, self.local.maintenance, self.local.maintenance_epoch = previous

    @contextmanager
    def control(self):
        """Reuse the current authorized lease, or acquire/release a short UI lease."""
        actor = getattr(self.local, "owner", None)
        if getattr(self.local, "maintenance", False) or (actor is not None and actor == self.owner):
            yield
            return
        actor = uuid4().hex
        if not self.claim(actor):
            raise MeterInterrupted(self.reason or "Meter controls are in use", self.epoch)
        try:
            with self.bind(actor):
                yield
        finally:
            self.release(actor)

    @contextmanager
    def recovery_control(self):
        """Yield permission only when idle or the job has explicitly handed off controls."""
        with self.condition:
            borrowed = self.owner is None
            allowed = borrowed or self.recovery_allowed
            if borrowed:
                self.owner = "recovery"
        if not allowed:
            yield False
            return
        try:
            with self.bind(maintenance=True):
                yield True
        finally:
            if borrowed:
                self.release("recovery")

    def action_checkpoint(self):
        """Reject foreign owners, stale attempts, retired sessions, or unavailable apps."""
        if getattr(self.local, "maintenance", False):
            if self.epoch != self.local.maintenance_epoch or self.stopped.is_set():
                raise MeterInterrupted("Meter changed during recovery", self.epoch)
            return
        with self.condition:
            if self.stopped.is_set():
                raise MeterInterrupted("session retired", self.epoch)
            if self.owner is not None and getattr(self.local, "owner", None) != self.owner:
                raise MeterInterrupted("controls owned by another operation", self.epoch)
            if not self.ready:
                raise MeterInterrupted(self.reason, self.epoch)
            shared = self.shared
            if shared is not None and not shared.lifecycle_observer:
                self.checkpoint(shared.attempt_epoch)

    def checkpoint(self, epoch):
        with self.condition:
            if self.stopped.is_set() or not self.ready or epoch != self.epoch:
                raise MeterInterrupted(self.reason or "meter changed during the attempt", self.epoch)

    def wait_ready(self, shared=None, timeout=None):
        """Permit recovery and return the ready epoch, or raise on cancel/deadline.

        The caller must unwind workers and robot/lamp actions before calling.
        ``timeout`` bounds this wait in seconds; the supervisor also maintains its
        session-wide recovery deadline. This does not bypass initial admission.
        """
        deadline = time.monotonic() + (self.recovery_timeout if timeout is None else timeout)
        with self.condition:
            self.recovery_allowed = True
            try:
                while not self.ready:
                    if shared is not None and shared.abort_event.is_set():
                        from lib.automation.helpers import StopAutomation
                        raise StopAutomation("Recovery cancelled by operator")
                    if self.stopped.is_set() or self.phase == "intervention" or time.monotonic() >= deadline:
                        raise RecoveryFailed(self.reason or "recovery deadline exceeded", self.epoch)
                    self.condition.wait(min(0.25, max(0.0, deadline - time.monotonic())))
                return self.epoch
            finally:
                self.recovery_allowed = False

    def set_desired(self, **values):
        with self.condition:
            self.desired.update(deepcopy(values))
            self.display_revision += 1

    def close(self):
        self.stopped.set()
        self.interrupt("Meter disconnected", phase="offline")
        if self.supervisor:
            self.supervisor.close()
