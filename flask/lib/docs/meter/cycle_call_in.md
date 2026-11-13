# Call-In Test: Transaction Proof and Lifecycle Handoff

`lib/automation/tests/cycle_call_in.py` drives **Service > Call In > +** and
validates the resulting MS3 transaction. `cycle_modem.py` checks modem control
and signal; this test checks the actual Session Agent exchange and teardown.
Real Call In runs require the `MeterSession` and its active supervisor. Normal
meter discovery attaches both before job admission; the virtual mock path
handles its Call In stage separately.

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
ConnectionServer client. The test discards an idle snapshot if the
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
- The meter has a continuously followed journal stream in
  `MeterSupervisor`. The test attaches a short-lived subscriber **before**
  pressing `+`. It collects platform and modem messages while the supervisor
  independently monitors readiness. This stream remains readable to the test
  after the supervisor blocks ordinary SSHMeter actions for an update. No
  Call In page or meter-status read is attempted after that restriction.
- A direct call with no active supervisor fails before navigating or pressing
  `+`, because it has no independent journal stream or lifecycle protection.

The stream is bounded to 6,000 lines for one attempt. `callIn` sends
bound the first transaction; modem evidence is also cut off before the next
send. If CIM returns to ready without a `callIn` send, the test allows five
seconds for follower lag and then fails that manual attempt; it does not wait
for a later scheduled call-in. It never presses `+` again after an in-flight
interruption. If live journal proof remains incomplete, the attempt fails with
its observed evidence; it does not wait through a restart to query the next
runtime. A journal gap can therefore produce a missing-proof failure, which is
distinguishable in metadata from an explicit `result=-1` response.

## Supervised flow

1. At each iteration, wait for session readiness and a connected supervisor
   journal follower before navigating or pressing `+`. The supervisor has
   already handled its startup/settling and diagnostics admission checks. The
   test has no separate history-based startup guard. Navigate to Call In,
   verify local idle status and stable `Press [+] to Call In.` page text, and
   save a baseline.
   A disruption before `+` retries navigation for that iteration; completed
   earlier iterations are retained.
2. Attach the live journal capture, set `call_in_in_flight` and
   `lifecycle_observer`, then press `+` once. The observer exemption permits
   this transaction to finish gathering proof after the supervisor changes
   epochs. It is cleared in the iteration's `finally` block.
3. Confirm the trigger from CIM leaving ready or the first captured `callIn`
   request. Watch CIM/CS/modem state and the journal until the matched response,
   Session Manager completion, connection use and release are proven. CIM
   returning to ready alone does not prove release: RSYNC or RunScript may
   still own the connection.
4. After complete proof, observe the independent journal for up to 20 seconds
   for config/update evidence and MS3 stop. This covers the observed updater
   delay without following a restarted runtime. An observed MS3 stop or later
   call-in ends the observation window early. When no restriction occurs,
   confirm terminal local idle status before handing the meter on.
5. If update/restart restricts status reads, decide from the captured journal.
   An updater decision can prove release because MS3 checks UI idle and no
   connection clients before applying it. Missing or failed proof fails the
   original attempt. `run_subtest` does not replay an in-flight call-in.

The call-in result can be recorded while the meter session is restricted.
Before another test or call-in iteration uses SSHMeter controls, its own
readiness gate waits through recovery. `cycle_all` and the top-level runner
also gate job completion on readiness. The test no longer needs a separate
post-update guard merely to protect later work.

`update_or_config_downloaded` is true when the transaction journal contains a
config write, printer-template installation, legacy-config installation, or
pending package/app configuration marker. RSYNC completion alone does not set
it. `restart_detected` is true when the supervisor's journal shows MS3
stopping, its phase enters `restarting`, or it observes a new MS3 generation
before the next `callIn` send. An updater *decision* by itself does not mean a
restart happened. False means **not observed within this transaction's
window**, not proof that a later unrelated update can never happen.

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

Across 24 archived post-press cases with both a `callInResponse` and a
subsequent updater marker, the largest observed interval was
11.734 seconds. This is why the managed path uses a configurable 20-second
post-proof window. The November 11 no-update desk capture shows response,
post-session client release and later idle status without an updater marker.
There is no positive journal line that certifies that no future update will
ever occur; the false metadata values are bounded observations.

The old code sometimes waited 75 to 180 more seconds after restart and could
collect a second startup call-in. That wait protected following subtests before
the supervisor existed; the original transaction's PASS/FAIL evidence was
already available. For historical timing and update/restart attribution, see
the October review under `wc_copy/debug production logs/2026-10-20 Various
Errors/10-20 Passive Call-In Reboot/`.

## Diagnosing a surprising result

Set **Settings > Passive > Call In > Debug** to `True` for additional
`DEBUG:` lines in the normal job/meter log. It defaults to `False`. Debug
records the observation timeouts and changes in live journal proof (line
count, matched reference, response, connection, release and missing criteria).
The ordinary
PASS/FAIL validation and essential transition logs remain active when debug
is off. The passive settings builder passes this toggle only to the Call In
subtest; direct callers can supply `debug=True` as a keyword argument.

Inspect `shared.device_meta["call_in"][cycle_number]` in the job summary:

- `phase`, `status`, `exception_type`, `total_elapsed_s` locate the failure.
- `baseline_snapshot`, `lifecycle_snapshot`, `cleanup_snapshot` and
  `lifecycle` show what status was actually observed. Raw status HTML is omitted.
- `evidence_source` is `supervisor_journal`. `journal_stream_connected` is
  the stream state at verdict time, not a guarantee of gap-free history.
- `update_or_config_downloaded`, `restart_detected`,
  `transition_observed_s`, `transition_observation_complete`, and
  `follow_on_call_in_seen` describe the bounded post-proof observation.
- `platform_evidence.call_in_reference`, `call_in_send_line`,
  `call_in_response_line`, `clients_released_after_session` and `update_line`
  identify the original transaction and teardown evidence.
- `modem_evidence`, `validation.connect_sources`,
  `validation.release_sources`, `validation.failures` and warnings explain the
  decision. Missing signal data alone is not a failure.

When a run has incomplete journal proof, inspect the meter session
log for `journal_disconnected`, `journal_gap`, update commitment,
generation changes and UI transition samples around the trigger.
If a response is missing, check whether a second `callIn` send ended the first
transaction's window and whether the first send/reference belongs to the
manual press. A failure after an in-flight trigger must not be fixed by
automatically pressing `+` again.

## Configuration and source references

`ready_timeout_s` (120 seconds) bounds journal reconnection and the local idle
status and Call In page pre-check. `ready_stable_s` (3 seconds) requires a stable
ready page. These are **not** a startup age timer; the supervisor handles
startup admission. `start_timeout_s` (20 seconds)
bounds request confirmation. `completion_timeout_s` (120 seconds) and
`disconnect_timeout_s` (45 seconds) bound original-transaction proof and local
idle cleanup when no restriction occurs. `state_poll_s` defaults to 2 seconds.
`transition_observe_s` defaults to 20 seconds after complete proof for update
and restart metadata. There is no Call In-specific recovery or post-restart
timeout. `job_count` is the number of complete transactions, and `subtest=True`
suppresses a duplicate progress broadcast.

MS3 source: `assets/ms3/main/UI/Diagnostics/DiagServiceMenu.c` triggers
`CIMCallInNow()`; `CallInManager.c` and `Services/ConnectionServer.c` own the
connection; `Meter.c` handles the response; `Updater.c` commits updates;
`MS3.c` schedules the post-startup call-in. The source uses
`RESTART_CALLIN_SECS = 60` despite a stale nearby “5 minutes” comment.
