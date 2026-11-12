# Call-In Test: Transaction Proof and Lifecycle Handoff

`lib/automation/tests/cycle_call_in.py` drives **Service > Call In > +** and
validates the resulting MS3 transaction. `cycle_modem.py` checks modem control
and signal; this test checks the actual Session Agent exchange and teardown.

## What constitutes PASS

Each requested cycle needs all of the following:

1. A call-in started (CIM left ready, or the platform journal sent `callIn`).
2. The connection path was used (PPP counter, observed CS/modem connected state,
   or modem journal connect evidence).
3. Session Agent sent `callIn` and received a `callInResponse` with the **same
   reference**, without `result=-1`. A missing result means success in the old
   MS3 source; only `-1` denotes the Session Agent connection failure.
4. `Session Manager Completed` or `Session complete` appeared within that
   transaction.
5. The connection was released. Valid sources include a later idle status
   snapshot, ordered modem/CS teardown, modem journal teardown, a
   latest `Clients that need a connection: (none)` platform state **after session
   completion**, or post-call updater activity. The first subsequent `callIn`
   send ends the transaction window, so a restarted runtime's startup call-in
   cannot supply the manual call-in's response or platform release proof.

An idle snapshot requires CIM `S1_WAITING_FOR_CALL_TIME` or `S4_SUSPENDED`, CS
`S5_DISCONNECTED` or `S6_ERROR`, modem `S1_IDLE` or `S7_ERROR`, and no named
ConnectionServer client. A supervised run discards an idle snapshot if the
session epoch changed before validation, since it could belong to the new
runtime. A terminal CS/modem error with a successful session
can pass with a teardown warning. RSSI/BER and a rise in PPP failed connects
are diagnostic information; neither alone fails the test. The initial idle
baseline never proves a *later* release.

## Data and ownership

- `cmd.main.meter:status` supplies CIM/CS/modem states, client names and PPP
  counters. The pre-check also requires the Call In page text `Press [+] to
  Call In.` rather than `Wait for the current Call In to complete.`
- `MS3_Platform.service` supplies the Session Agent request, matched response,
  session events, client release and updater markers.
- `MS3_Modem.service` supplies connection and signal markers.
- A managed meter has a continuously followed journal stream in
  `MeterSupervisor`. The test attaches a short-lived subscriber **before**
  pressing `+`. It collects platform and modem messages while the supervisor
  independently monitors readiness. This stream remains readable to the test
  after the supervisor blocks ordinary SSHMeter actions for an update.
- A meter without a supervisor keeps the older direct journal-query and
  recovery path. The history-based startup guard and post-recovery guard are
  only used there.

The managed stream is bounded to 6,000 lines for one attempt. `callIn` sends
bound the first transaction; modem evidence is also cut off before the next
send. If CIM returns to ready without a `callIn` send, the test allows five
seconds for follower lag and then fails that manual attempt; it does not wait
for a later scheduled call-in. If live capture misses other required proof
(for example, a journal reconnect or cursor gap), the test waits for readiness
once and queries service journals
with the original pre-press meter-time watermark. It never presses `+` again
after an in-flight interruption. A real Linux reboot may erase previous-boot
journal data, so the live capture is the primary proof in that case. A fetched
request is accepted only if it matches the captured send line, or if no send
was captured and the supervised epoch never changed. This prevents the
post-restart startup call-in from filling a gap in the manual transaction.

## Supervised flow

1. At each iteration, wait for session readiness. The supervisor has already
   handled the fresh-runtime startup window, startup call-in, diagnostics entry,
   client idle state and stable UI. Navigate to Call In, verify local idle
   status and the Call In page text, and save a baseline and journal watermark.
   A disruption before `+` retries navigation for that iteration; completed
   earlier iterations are retained.
2. Attach the live journal capture, set `call_in_in_flight` and
   `lifecycle_observer`, then press `+` once. The observer exemption permits
   this transaction to finish gathering proof after the supervisor changes
   epochs. It is cleared in the iteration's `finally` block.
3. Watch CIM/CS/modem state and evaluate the live transaction. On a stable
   runtime, wait for a terminal idle status before returning. CIM may return
   to ready while RSYNC or RunScript still owns the connection, so that state
   alone does not pass. A cleanup timeout can still validate from independent
   release proof, as the earlier test did.
4. If update/restart makes status unavailable, keep reading the already
   captured journal. Allow a short stream catch-up. An updater commitment can
   stand in for local terminal status because it invalidates controls through
   supervision. A complete verdict needs no wait for the new runtime's startup
   call-in or 75-second settling gate.
5. If proof remains incomplete, wait for supervisor readiness and make one
   direct journal-query fallback. Missing or failed proof then fails the
   original attempt. `run_subtest` does not replay an in-flight call-in.

The call-in result can be recorded while the meter session is restricted.
Before another test or call-in iteration uses SSHMeter controls, its own
readiness gate waits through recovery. `cycle_all` and the top-level runner
also gate job completion on readiness. The test no longer needs a separate
post-update guard merely to protect later work.

## Why the earlier verdict is justified

October 2026 production `*cycle_all*.log` files were reviewed excluding meter
IDs `12003859`, `30000269`, `30001189`, and `30002014`. Among 47 logs with an
update commitment after the test's `+` press, 46 show the first `callIn` send
before CIM returned to ready (or before the update where no ready return was
logged). Their Session Agent completion and matched response appeared before
the updater commitment. Forty-four of those 46 also emitted a post-session
`Clients that need a connection: (none)` line before commitment. In two slower
traces
(`2026-10-06/07-18-13_30004914_cycle_all.log` and
`2026-10-09/10-14-37_30005467_cycle_all.log`), those explicit release lines
were absent before the update marker; the updater commitment is the earliest
available release proof. It is meaningful because MS3's updater runs only
after the connection need has cleared and the UI is idle. These records
support deciding the original transaction at or before update commitment,
without using a later startup call-in's proof. These older logs primarily
contain platform journal and sampled status; they do not independently cover
all modem journal or UI evidence.

The October 27 `12-38-26_30005774_cycle_all.log` is an especially useful edge
case: the manual `+` initially returned CIM to ready without a `callIn` send,
then a later call-in did produce the first `callIn` and update. Keep the
watermark and reference matching, and end that manual attempt when CIM returns
without a send. The November 11 desk-meter capture
`logs/2026-11-11/14-27-04_30001189.log` shows the no-update path, including
full journals and UI sampling, but cannot establish update-page timing.
The October 27 physical log `09-18-24_30005820_physical_cycle_all.log`
does capture the Notice page text `This meter is being updated. Please wait.`;
the supervisor classifies that HTML as a transition and restricts controls.

The old code sometimes waited 75 to 180 more seconds after restart and could
collect a second startup call-in. That wait protected following subtests before
the supervisor existed; the original transaction's PASS/FAIL evidence was
already available. For historical timing and update/restart attribution, see
the October review under `wc_copy/debug production logs/2026-10-20 Various
Errors/10-20 Passive Call-In Reboot/`.

## Diagnosing a surprising result

Set **Settings > Passive > Call In > Debug** to `True` for additional
`DEBUG:` lines in the normal job/meter log. It defaults to `False`. Debug
records the selected execution mode and timeouts, changes in live journal
proof (line count, matched reference, response, connection, release and missing
criteria), and direct journal fallback coverage/identity checks. The ordinary
PASS/FAIL validation and essential transition logs remain active when debug
is off. The passive settings builder passes this toggle only to the Call In
subtest; direct callers can supply `debug=True` as a keyword argument.

Inspect `shared.device_meta["call_in"][cycle_number]` in the job summary:

- `phase`, `status`, `exception_type`, `total_elapsed_s` locate the failure.
- `baseline_snapshot`, `lifecycle_snapshot`, `cleanup_snapshot` and
  `lifecycle` show what status was actually observed. Raw status HTML is omitted.
- `evidence_source` is `supervisor_journal` for the normal managed path or
  `post_recovery_journals` after its fallback. Legacy runs retain their older
  cleanup/recovery fields. `journal_stream_connected` is the stream state at
  verdict time, not a guarantee of gap-free history.
- `platform_evidence.call_in_reference`, `call_in_send_line`,
  `call_in_response_line`, `clients_released_after_session` and `update_line`
  identify the original transaction and teardown evidence.
- `modem_evidence`, `validation.connect_sources`,
  `validation.release_sources`, `validation.failures` and warnings explain the
  decision. Missing signal data alone is not a failure.

When a managed run unexpectedly uses the journal fallback, inspect the meter
session log for `journal_disconnected`, `journal_gap`, update commitment,
generation changes and UI transition samples around the saved watermark.
If a response is missing, check whether a second `callIn` send ended the first
transaction's window and whether the first send/reference belongs to the
manual press. A failure after an in-flight trigger must not be fixed by
automatically pressing `+` again.

## Configuration and source references

`ready_timeout_s` / `ready_stable_s` govern the local pre-check;
`start_timeout_s`, `completion_timeout_s`, `disconnect_timeout_s` and
`state_poll_s` govern observation and proof collection. `recovery_timeout_s`
governs the managed journal fallback. `platform_journal_max_lines` and
`modem_journal_max_lines` bound direct fallback queries. The remaining
`startup_guard_s`, `startup_platform_journal_max_lines`,
`post_completion_grace_s`, `post_recovery_guard_s`,
`post_recovery_timeout_s` and `status_loss_grace_s` primarily support the
legacy path or status-loss detection. `job_count` is the number of complete
transactions, and `subtest=True` suppresses a duplicate progress broadcast.

MS3 source: `assets/ms3/main/UI/Diagnostics/DiagServiceMenu.c` triggers
`CIMCallInNow()`; `CallInManager.c` and `Services/ConnectionServer.c` own the
connection; `Meter.c` handles the response; `Updater.c` commits updates;
`MS3.c` schedules the post-startup call-in. The source uses
`RESTART_CALLIN_SECS = 60` despite a stale nearby “5 minutes” comment.
