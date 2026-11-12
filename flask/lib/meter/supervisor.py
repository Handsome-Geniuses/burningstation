"""Continuous, bounded observation and idle/relinquished-control recovery.

Two independent SSH clients keep journal following and health observations off
the job's command transport. Existing tests retain their own proof queries.

Keep ``lib/docs/meter/supervisor.md`` in sync when changing sampling, phase,
logging, configuration, or recovery behavior here.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
import shlex
import threading
import time
import traceback
from html import unescape

import paramiko

from lib.meter.lifecycle import MeterInterrupted


LOG_ROOT = Path(__file__).resolve().parents[2] / "logs"


def monitoring_option(name, environment):
    """Read a live Settings value, with an explicit environment override if set."""
    override = os.getenv(environment)
    if override is not None:
        return override.lower() in {"1", "true", "yes", "on"}
    from lib.store import store
    return getattr(store.settings.meter_monitoring, name)


UNITS = ("MS3_Platform.service", "MS3_Modem.service", "MS3_RunOnce.service")
JOURNAL = "journalctl --no-pager -o json " + " ".join(f"-u {unit}" for unit in UNITS)
HEALTH = (
    "printf 'boot_id='; cat /proc/sys/kernel/random/boot_id; "
    "printf 'hostname='; hostname; "
    "systemctl show MS3_Platform.service -p MainPID -p ActiveState "
    "-p ExecMainStartTimestampMonotonic && printf '\\n__health_end__\\n'"
)


def page_kind(html):
    """Classify raw/returned HTML for guards; ordinary notices are usable pages."""
    text = re.sub(r"<[^>]+>", " ", html or "").lower()
    if ("this meter is being updated" in text or "restarting" in text
            or re.search(r"class\s*=\s*[\"']?noticetitle[^>]*>.*?\bupdate\b", html or "", re.I | re.S)):
        return "transition"
    if not html or "unable to open file" in text or "no such file" in text:
        return "unavailable"
    if re.search(r"class\s*=\s*[\"']?diag(?:title|content|info)", html, re.I):
        return "diagnostics"
    return "other" if "<html" in html.lower() else "unknown"


def fields(text):
    return dict(re.findall(r"^\s*([\w]+)\s*[:=]\s*(.*?)\s*$", text or "", re.M))


def complete_health(sample):
    """Distinguish missing output from explicit stopped-service values (PID/start 0)."""
    return (bool(sample.get("boot_id")) and bool(sample.get("hostname"))
            and sample.get("MainPID", "").isdigit()
            and sample.get("ExecMainStartTimestampMonotonic", "").isdigit()
            and bool(sample.get("ActiveState")))


def transition_reason(message):
    """Return (phase, reason) for late commitment/sleep evidence, otherwise None."""
    # Deliberately late signals. Config delivery/Rsync/printer transfers are
    # useful context, but must not abort an otherwise productive subtest.
    if "PowerServer:sHandleTimerEvent: Grace period timeout" in message:
        return "sleep", "Meter entering sleep"
    if re.search(r'"command"\s*:\s*"platformSleep"', message):
        return "sleep", "Meter entering sleep"
    if ("UpdaterCheckForUpdates: Installing legacy config" in message
            or "UpdaterCheckForUpdates: Restarting, to use new legacy config" in message
            or re.search(r"UpdaterCheckForUpdates: (?:package|appCfg|appOverlay) update is pending", message)
            or "UpdaterCheckForUpdates: invoking update" in message):
        return "updating", "MS3 applying an update"
    if "Stopping MS3 Platform" in message or "Watchdog timeout" in message:
        return "restarting", "MS3 restarting"
    return None


def journal_message_for_log(message):
    """Keep one readable line while excluding raw card-read payloads from logs."""
    message = str(message or "")
    message = re.sub(r"(\bCARD_READ_DATA\b).*", r"\1 [payload redacted]", message,
                     flags=re.IGNORECASE | re.DOTALL)
    return message.replace("\r", "\\r").replace("\n", "\\n")


class MeterSupervisor:
    """Own continuous evidence capture and recover only idle/relinquished controls.

    ``session`` belongs to one discovery, not one test or application generation.
    Journal and health workers use independent SSH connections; job commands use
    SSHMeter's separate transport. One thread-safe text log receives all journal,
    changed UI, discovery/admission decisions, and SharedState job output. See the
    companion documentation for readiness proof and why early update clues do not
    stop tests. Constructing this object does not start threads or contact a meter.
    """
    _discovery_log_lock = threading.Lock()

    def __init__(self, session, *, poll_s=1.0):
        self.session = session
        self.meter = session.meter
        self.poll_s = poll_s
        self.clients = set()
        self.client_lock = threading.Lock()
        self.threads = []
        self.diag_records = []
        self.proof_after = (None, 0)
        self.requires_diags_proof = False
        self.last_notice = 0.0
        self.idle_since = None
        self.next_press = 0.0
        self.last_published = None
        self.handler = None
        self.log_lock = threading.RLock()
        self.log_path = None
        self.log_closed = False
        self.pending_lines = []
        self.pending_chars = 0
        self.last_flush = time.monotonic()
        self.journal_sources = {}
        self.cursor = None
        self.automatic_recovery = os.getenv("METER_SUPERVISOR_RECOVERY", "1") == "1"
        self.last_ui = {}
        self.last_observation_error = None

    @property
    def capture_ui(self):
        return monitoring_option("capture_ui", "METER_CAPTURE_UI")

    @property
    def debug_enabled(self):
        return monitoring_option("debug", "METER_SUPERVISOR_DEBUG")

    def _debug(self, decision, **data):
        """Optional per-sample decisions go to the lifecycle log and terminal."""
        if self.debug_enabled:
            self._log("debug", decision=decision, **data)
            print(f"[meter {self.meter.hostname} {self.meter.host}] {decision}: {json.dumps(data, default=str)}")

    @classmethod
    def discovery_log(cls, event, ip, **data):
        """Save pre-identity SSH failures, which cannot safely belong to a known meter.

        Identified-meter decisions use that session's own log instead. This small
        station log explains why an address has not produced a session/card yet.
        """
        now = datetime.now()
        row = {"event": event, "ip": ip, "received_utc": datetime.now(timezone.utc).isoformat(), **data}
        with cls._discovery_log_lock:
            directory = LOG_ROOT / now.strftime("%Y-%m-%d")
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "discovery.log").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, default=str) + "\n")
        if monitoring_option("debug", "METER_SUPERVISOR_DEBUG"):
            print(f"[meter discovery] {json.dumps(row, default=str)}")

    def _log(self, event, **data):
        with self.log_lock:
            self._write_log(event, **data)

    def _write_log(self, event, **data):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if event == "journal":
            record = data["journal"]
            metadata = {key: record[key] for key in
                        ("__REALTIME_TIMESTAMP", "__MONOTONIC_TIMESTAMP", "__CURSOR")
                        if key in record}
            unit = record.get("_SYSTEMD_UNIT")
            if unit and unit != "MS3_Platform.service":
                metadata["_SYSTEMD_UNIT"] = unit
            message = journal_message_for_log(record.get("MESSAGE", ""))
            self.write_line(f"[{timestamp}] supervisor.journal: {message} | "
                            f"{json.dumps(metadata, ensure_ascii=False, separators=(',', ':'), default=str)}")
            return
        row = {"event": event, "received_utc": datetime.now(timezone.utc).isoformat(),
               "session_id": self.session.id, **data}
        if event in {"job_started", "job_finalized", "session_started", "session_closed"}:
            label = {"job_started": "RUNNING", "job_finalized": "FINISHED",
                     "session_started": "METER DETECTED", "session_closed": "METER REMOVED"}[event]
            self.write_line(f"\n{'=' * 25} {label} {str(data.get('program', self.meter.hostname)).upper()} {'=' * 25}")
        self.write_line(f"[{timestamp}] supervisor.{event}: {json.dumps(row, ensure_ascii=False, default=str)}")

    def write_line(self, line):
        """Queue complete entries atomically; flush in bounded batches.

        SharedState uses this same writer, avoiding concurrent file handles,
        or a second per-job file. The monitor flushes each poll, jobs flush at
        finalization, and close drains the buffer. A full batch flushes early.
        """
        with self.log_lock:
            if self.log_closed:
                return
            self._ensure_log()
            self.pending_lines.append(line + "\n")
            self.pending_chars += len(line) + 1
            if self.pending_chars >= 64 * 1024 or time.monotonic() - self.last_flush >= 2:
                self._flush_pending_locked()

    def _flush_pending_locked(self):
        if self.handler and self.pending_lines:
            self.handler.stream.write("".join(self.pending_lines))
            self.handler.flush()  # Python flush, not fsync; the OS may still cache writes.
            self.pending_lines.clear()
            self.pending_chars = 0
            self.last_flush = time.monotonic()

    def flush_log(self):
        """Drain pending lines without closing the session log when a job ends."""
        with self.log_lock:
            self._flush_pending_locked()

    def _ensure_log(self):
        if self.handler is None:
            host = re.sub(r"[^a-zA-Z0-9_.-]", "_", self.meter.hostname)
            now = datetime.now()
            path = LOG_ROOT / now.strftime("%Y-%m-%d")
            path.mkdir(parents=True, exist_ok=True)
            stem = f"{now.strftime('%H-%M-%S')}_{host}"
            suffix = 1
            while True:
                # Exclusive creation preserves both lifetime logs if this same
                # meter is detected twice within one second.
                name = f"{stem}{'' if suffix == 1 else f'_{suffix}'}.log"
                candidate = path / name
                try:
                    handler = logging.FileHandler(candidate, mode="x", encoding="utf-8")
                except FileExistsError:
                    suffix += 1
                    continue
                self.log_path = str(candidate)
                self.handler = handler
                break
            self.handler.setFormatter(logging.Formatter("%(message)s"))

    def _connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.meter.host, username=self.meter.user, password=self.meter.pswd,
                           timeout=2, auth_timeout=2, banner_timeout=2)
        except Exception:
            client.close()
            raise
        client.get_transport().set_keepalive(5)
        with self.client_lock:
            self.clients.add(client)
        return client

    def _drop(self, client):
        if client:
            client.close()
            with self.client_lock:
                self.clients.discard(client)

    def _command(self, client, command, timeout=4):
        """Read a short SSH command under a total deadline, including exit status."""
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        channel = stdout.channel
        end = time.monotonic() + timeout
        out, err = bytearray(), bytearray()
        try:
            while not self.session.stopped.is_set():
                if channel.recv_ready():
                    out.extend(channel.recv(65536))
                if channel.recv_stderr_ready():
                    err.extend(channel.recv_stderr(65536))
                finished = channel.exit_status_ready() and (channel.eof_received or channel.closed)
                if finished and not channel.recv_ready() and not channel.recv_stderr_ready():
                    code = channel.recv_exit_status()
                    if code:
                        raise RuntimeError(err.decode(errors="replace") or f"Command exited {code}")
                    return out.decode(errors="replace")
                if time.monotonic() >= end:
                    raise TimeoutError("Meter observation exceeded its deadline")
                self.session.stopped.wait(0.025)
            raise InterruptedError("Session stopping")
        finally:
            channel.close()

    def _read_health(self, client):
        """Quickly retry incomplete output; never turn missing fields into a new PID."""
        for attempt in range(2):
            result = self._command(client, HEALTH)
            if "__health_end__" in result and complete_health(fields(result)):
                return result
            self._log("health_sample_incomplete", attempt=attempt + 1, raw=result)
        raise RuntimeError("Incomplete meter health response after immediate retry")

    def _read_raw_ui(self, client):
        """Reread a blank file once: normal UI rewrites can briefly expose an empty file."""
        for attempt in range(2):
            html = self._command(client, "cat /var/volatile/html/UI_0.html")
            self.record_ui(source="ssh:UI_0.html", html=html)
            if html.strip() or attempt:
                return html
            self._debug("blank_ui_reread", source="ssh:UI_0.html")
            self.session.stopped.wait(0.05)

    def journal_record(self, record, *, history=False):
        """Save a compact line; retain full records in memory for live monitors."""
        unit = record.get("_SYSTEMD_UNIT", "")
        identity = (record.get("_BOOT_ID"), record.get("_PID"),
                    record.get("_SYSTEMD_INVOCATION_ID"))
        if any(identity) and self.journal_sources.get(unit) != identity:
            self.journal_sources[unit] = identity
            self._log("journal_source_changed", unit=unit or None, boot_id=identity[0],
                      pid=identity[1], invocation_id=identity[2])
        self._log("journal", journal=record)
        self.cursor = record.get("__CURSOR", self.cursor)
        message = str(record.get("MESSAGE", ""))
        if "DiagnosticsEnter: ENTER DIAGS" in message:
            with self.session.condition:
                self.diag_records.append((record.get("_BOOT_ID", ""), int(record.get("__MONOTONIC_TIMESTAMP", 0))))
                self.diag_records = self.diag_records[-32:]
        if not history:
            reason = transition_reason(message)
            if reason:
                self.requires_diags_proof = True
                self.proof_after = (str(record.get("_BOOT_ID", "")).replace("-", ""),
                                    int(record.get("__MONOTONIC_TIMESTAMP", 0)))
                self.last_notice = time.monotonic()
                self.session.interrupt(reason[1], phase=reason[0])
            with self.session.condition:
                subscribers = tuple(self.session.subscribers)
            for subscriber in subscribers:
                subscriber.log(journal_message_for_log(message), source="supervisor.journal", persist=False)
    def record_ui(self, *, source, html=None, error=None):
        """Persist changed raw HTML/read errors from health AND job navigation.

        Sources stay separate (raw SSH file versus rendered HTTP/PHP fallback),
        since overlays may differ. Repeated identical samples are suppressed;
        a successful read after an error is always recorded, even if HTML repeats.
        """
        value = (html, str(error) if error is not None else None)
        with self.log_lock:
            if self.last_ui.get(source) == value:
                return
            self.last_ui[source] = value
            if self.capture_ui:
                text = unescape(re.sub(r"<[^>]+>", " ", html or ""))
                self._log("ui_error" if error is not None else "ui_changed", source=source,
                          html=html, text=" ".join(text.split()), error=value[1])

    def _journal(self):
        """Backfill bounded history, follow continuously, and resume cursors after loss.

        Initial history is context only. Live catchup is processed before the
        journal-connected admission gate opens; stale/invalid cursors are logged.
        """
        cursor = None
        while not self.session.stopped.is_set():
            client = channel = None
            try:
                client = self._connect()
                if cursor is None:
                    text = self._command(client, JOURNAL + " -b 0 -n 300", timeout=10)
                    self._log("journal_history_start", count=len(text.splitlines()))
                    for line in text.splitlines():
                        record = json.loads(line)
                        self.journal_record(record, history=True)
                        cursor = record.get("__CURSOR", cursor)
                    self._log("journal_history_end", cursor=cursor)
                tail = self._command(client, JOURNAL + " -n 1", timeout=4)
                tail_records = [json.loads(line) for line in tail.splitlines() if line.strip()]
                caught_up_cursor = tail_records[-1].get("__CURSOR") if tail_records else cursor
                command = JOURNAL + " -f " + ("--after-cursor=" + shlex.quote(cursor) if cursor else "-n0")
                _, stdout, stderr = client.exec_command(command, timeout=3)
                channel = stdout.channel
                self.session.journal_connected = cursor == caught_up_cursor
                self._log("journal_connected", cursor=cursor)
                self._log("journal_stream_started", after_cursor=cursor,
                          catchup_cursor=caught_up_cursor)
                buffer = bytearray()
                heartbeat = time.monotonic()
                while not self.session.stopped.is_set():
                    if channel.recv_ready():
                        buffer.extend(channel.recv(65536))
                        if len(buffer) > 8 * 1024 * 1024:
                            raise RuntimeError("Journal record exceeds buffer limit")
                        while b"\n" in buffer:
                            line, _, buffer = buffer.partition(b"\n")
                            if not line.strip():
                                continue
                            record = json.loads(line)
                            self.journal_record(record)
                            cursor = record.get("__CURSOR", cursor)
                            if cursor == caught_up_cursor:
                                self.session.journal_connected = True
                    if channel.exit_status_ready() and not channel.recv_ready():
                        # An invalid/expired cursor must be reported, never
                        # silently treated as complete journal coverage.
                        error = stderr.read().decode(errors="replace")
                        if channel.recv_exit_status() != 0:
                            self._log("journal_gap", reason=error, cursor=cursor)
                            cursor = None
                        raise ConnectionError("Journal follow ended: " + error)
                    if time.monotonic() - heartbeat >= 5:
                        self._command(client, "printf journal-health", timeout=2)
                        heartbeat = time.monotonic()
                    self.session.stopped.wait(0.05)
            except Exception as exc:
                self.session.journal_connected = False
                self._log("journal_disconnected", error=str(exc), cursor=cursor)
            finally:
                if channel:
                    channel.close()
                self._drop(client)
            self.session.stopped.wait(2)

    def observe(self, health, runtime, status, html):
        """Apply decoded health/runtime/status/UI observations without doing reads.

        Generation/late evidence invalidates work; descriptive phases then explain
        the remaining gate. A job may intentionally leave diagnostics while it
        owns controls. Recovery requires idle clients, live runtime, fresh diags
        evidence after disruption, minimum app age, and stable follow-up samples.
        """
        s = self.session
        h, app = fields(health), fields(runtime)
        if not complete_health(h):
            self._log("health_sample_incomplete", raw=health, decision="Ignoring incomplete generation observation")
            return  # _monitor retries/rejects these before reaching observe().
        active = h.get("ActiveState") == "active" and h.get("MainPID") not in (None, "0")
        started = h.get("ActiveState") in {"active", "activating", "reloading"} and h.get("MainPID") not in (None, "0")
        age = int(app["Runtime_sec"]) if app.get("Runtime_sec", "").isdigit() else None
        with s.condition:
            s.runtime_sec = age
            s.startup_remaining_s = max(0, 75 - age) if age is not None else None
            s.stable_remaining_s = None
        self._debug("health_sample", health=h, runtime=app, status=status, ui=page_kind(html),
                    owner=s.owner, recovery_allowed=s.recovery_allowed)
        generation = (h.get("boot_id"), h.get("MainPID"), h.get("ExecMainStartTimestampMonotonic"))
        if h.get("hostname") != self.meter.hostname:
            s.identity_mismatch = True
            s.interrupt("Different meter at this IP; reconnect required", phase="intervention")
            return
        if generation != s.generation:
            with s.condition:
                previous = s.generation
                s.generation = generation
                s.display_applied = None
                self.idle_since = None
                if previous is not None:
                    self.requires_diags_proof = True
                    s.interrupt("Linux reboot" if previous[0] != generation[0] else "MS3 generation changed",
                                new_generation=True)
                    for key in ("_firmwares", "_module_details_cache", "_module_info_cache", "_system_versions_cache", "_meter_region_cache"):
                        setattr(self.meter, key, None)
            self._log("generation", before=previous, after=generation)
        kind = page_kind(html)
        s.link, s.ui = "reachable", kind
        if kind == "transition":
            self.requires_diags_proof = True
            self.last_notice = time.monotonic()
            booting = active and age is not None and age < 75
            s.interrupt("MS3 started; waiting for startup/UI" if booting else "MS3 Update/Restart page",
                        phase="booting" if booting else "updating")
            return
        if not active or app.get("System_state") != "S4_RUNNING" or age is None:
            s.interrupt("MS3 service started; waiting for app runtime" if started else "Waiting for MS3 service to start",
                        phase="booting" if started else "restarting")
            self.idle_since = None
            return
        if not s.ready:
            s.describe("booting" if age < 75 else "recovering",
                       "MS3 running; startup settling" if age < 75
                       else "Checking diagnostics and client idle state")
        if kind not in ("diagnostics", "other"):
            s.interrupt("MS3 started; waiting for usable UI", phase="booting" if age < 75 else "recovering")
            self.idle_since = None
            return
        with s.condition:
            may_control = s.owner is None or s.recovery_allowed
            boot = str(generation[0]).replace("-", "")
            start = int(generation[2] or 0)
            if self.proof_after[0] == boot:
                start = max(start, self.proof_after[1])
            proof = any(b.replace("-", "") == boot and stamp >= start for b, stamp in self.diag_records)
        if not s.ready and not may_control:
            s.describe("booting" if age < 75 else "recovering", "Waiting for job workers to release controls for recovery")
            return
        if may_control and kind == "other":
            if s.ready:
                s.interrupt("Idle meter left diagnostics")
            self.idle_since = None
            if not self.automatic_recovery:
                s.describe("recovering", "Waiting for operator to enter diagnostics; automatic recovery disabled")
                return
            if time.monotonic() >= self.next_press:
                self.next_press = time.monotonic() + 2
                with s.recovery_control() as allowed:
                    if not allowed:
                        return
                    self.meter.press("diagnostics")
                self._log("diagnostics_press")
            s.describe("booting" if age < 75 else "recovering", "Entering diagnostics before readiness checks")
            return
        # During a job, other usable pages are intentional. Only recovery owns
        # the diagnostics baseline. Initial admission can accept existing diags;
        # after a disruption require current-generation ENTER DIAGS evidence.
        if not s.ready:
            if kind != "diagnostics" or (self.requires_diags_proof and not proof):
                self.idle_since = None
                s.describe("booting" if age < 75 else "recovering", "Waiting for current-generation diagnostics-entry journal evidence")
                return
        idle = (re.search(r"Clients requesting connection:\s*\(?none\)?", status, re.I) is not None
                and re.search(r"CIM:\s*state=S[14]_", status) is not None)
        # Runtime age is only a minimum settling heuristic, not proof that this
        # generation's startup call-in has occurred. Archived production logs
        # (2026-10-19: 09-47-21_30005988 and 11-28-28_30005989; 2026-10-20:
        # 10-05-03_30005980) show S4_RUNNING followed by a quiet interval, power
        # grace timeout, sleep/wake, timer refresh, then a startup marker. Their
        # listener timestamps are receipt times, so exact meter timing is unknown.
        # A 2026-11-12 desk-meter sleep capture confirms Runtime_sec advanced
        # 31 -> 121 across sleep with unchanged Start_time/generation; its startup
        # marker followed wake's TimerRefresh. See wc_copy/test/ms3_sleep/
        # 20261112_135534_192.168.69.138_sleepv2.log (lines 856, 908, 944, 1126).
        # TODO: Validate a sleep-aware/current-generation startup-call-in gate
        # before treating age >= 75 as settled; age itself includes sleep time.
        if not idle or age < 75 or time.monotonic() - self.last_notice < 3:
            self.idle_since = None
            if age < 75:
                s.describe("booting", "MS3 running; startup settling")
            else:
                s.describe("settling", "Waiting for call-in clients and update activity to settle")
            return
        if self.idle_since is None:
            self.idle_since = time.monotonic()
        if not s.ready:
            s.stable_remaining_s = max(0, math.ceil(3 - (time.monotonic() - self.idle_since)))
            s.describe("settling", "Verifying stable diagnostics and idle clients")
        if not s.ready and time.monotonic() - self.idle_since >= 3:
            if s.display_applied != (s.generation, s.display_revision):
                s.describe("restoring", "Restoring saved meter display and brightness")
                self._restore_display()
                return  # Verify a new health/UI sample after restoration.
            s.mark_ready()
            self._log("ready", generation=generation)

    def _restore_display(self):
        """Replay saved volatile UI intent under recovery ownership, then reverify."""
        s = self.session
        with s.condition:
            desired, revision = deepcopy(s.desired), s.display_revision
        self._log("display_restore_started", generation=s.generation, revision=revision, mode=desired["mode"])
        if not self.automatic_recovery:
            if desired["mode"] != "stock" or desired["brightness"] is not None:
                s.phase, s.reason = "intervention", "Automatic recovery disabled; restore the meter before continuing"
                return
            s.display_applied = (s.generation, revision)
            return
        with s.recovery_control() as allowed:
            if not allowed:
                return
            if desired["mode"] != "stock":
                self.meter.setup_custom_display()
                from lib.meter.display_utils import write_results_json, write_banner_json
                if desired["results"] is not None:
                    write_results_json(self.meter, desired["results"])
                write_banner_json(self.meter, desired["banner"])
                # Refresh without force_diagnostics()'s exit/re-entry toggles.
                self.meter.cli("printf %s " + shlex.quote(desired["mode"]) + " > /var/volatile/html/.ui_mode")
                self.meter.force_diagnostics()
            if desired["brightness"] is not None:
                self.meter.set_brightness(desired["brightness"])
        s.display_applied = (s.generation, revision)
        self._log("display_restored", generation=s.generation, revision=revision)

    def _publish(self):
        """Report changed gates/countdowns; elapsed uptime alone is not a transition."""
        snapshot = self.session.snapshot()
        previous = self.last_published
        if previous is not None and all(previous.get(key) == value for key, value in snapshot.items()
                                        if key != "runtime_sec"):
            return
        self.last_published = snapshot
        if previous is None or (previous["phase"], previous["reason"]) != (snapshot["phase"], snapshot["reason"]):
            before = previous["phase"] if previous else "identified"
            print(f"[meter {self.meter.hostname} {self.meter.host}] {before} -> {snapshot['phase']}: "
                  f"{snapshot['reason'] or 'Ready for testing'}")
        self._log("lifecycle", snapshot=snapshot)
        from lib.sse.sse_queue_manager import SSEQM
        SSEQM.broadcast("meter", {"ip": self.meter.host, "alive": True,
                                   "info": self.meter.public_info()})

    def _monitor(self):
        """Sample short commands; failures retain their stage and returned context in logs."""
        client = None
        while not self.session.stopped.is_set():
            health_ok = False
            stage = "ssh_connect"
            try:
                if client is None:
                    client = self._connect()
                stage = "health"
                health = self._read_health(client)
                health_ok = True
                stage = "runtime"
                runtime = self._command(client, "printf cmd.status | socat -T 2 - UDP:127.0.0.1:8008")
                stage = "client_status"
                status = self._command(client, "printf cmd.main.meter:status | socat -T 2 - UDP:127.0.0.1:8008")
                stage = "raw_ui"
                html = self._read_raw_ui(client)
                stage = "readiness_recovery"
                self.observe(health, runtime, status, html)
                if self.last_observation_error is not None:
                    self._log("observation_recovered", previous=self.last_observation_error)
                    self.last_observation_error = None
            except Exception as exc:
                error = (stage, str(exc))
                if error != self.last_observation_error:
                    self._log("observation_error", stage=stage, error=str(exc),
                              exception_type=type(exc).__name__, traceback=traceback.format_exc())
                    self.last_observation_error = error
                self._debug("observation_failed", stage=stage, error=str(exc))
                if stage == "raw_ui":
                    self.record_ui(source="ssh:UI_0.html", error=exc)
                self.session.link = "reachable" if health_ok else "unavailable"
                running = health_ok and fields(health).get("ActiveState") in {"active", "activating", "reloading"}
                booting = running and (self.session.runtime_sec is None or self.session.runtime_sec < 75)
                phase = ("sleep" if self.session.sleep_pending else "recovering" if stage == "readiness_recovery"
                         else "booting" if booting else "recovering" if running else "restarting" if health_ok else "offline")
                context = "Meter recovery action failed: " if stage == "readiness_recovery" else "Meter observation unavailable: "
                self.session.interrupt(context + str(exc), phase=phase)
                self.idle_since = None
                if not health_ok:
                    self._drop(client)
                    client = None
            if (not self.session.ready and time.monotonic() - self.session.recovery_since
                    >= self.session.recovery_timeout):
                self.session.phase = "intervention"
                self.session.reason = "Recovery timed out; check meter power, wake it, or reconnect"
            try:
                self._publish()
            except Exception:
                logging.exception("Unable to publish meter lifecycle")
            self.flush_log()
            self.session.stopped.wait(self.poll_s)
        self._drop(client)

    def start(self):
        """Open the discovery's log before launching independent observation workers."""
        self.session.supervisor = self
        self._log("session_started", ip=self.meter.host, hostname=self.meter.hostname,
                  capture_ui=self.capture_ui, debug=self.debug_enabled, automatic_recovery=self.automatic_recovery)
        self.flush_log()
        print(f"[meter {self.meter.hostname} {self.meter.host}] Lifecycle log: {self.log_path}")
        for name, target in (("journal", self._journal), ("health", self._monitor)):
            thread = threading.Thread(target=target, name=f"meter:{self.meter.host}:{name}", daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        """Close observation clients/workers and the lifetime log, never at job end."""
        with self.client_lock:
            clients = tuple(self.clients)
        for client in clients:
            client.close()
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=6)
        with self.log_lock:
            self._log("session_closed", reason=self.session.reason)
            self._flush_pending_locked()
            self.log_closed = True
            if self.handler:
                self.handler.close()
