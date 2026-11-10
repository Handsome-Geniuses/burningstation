# Meter lifecycle policy

Implementation contracts and the step-by-step call flow are in
[supervisor.md](supervisor.md). Update both documents with changes to supervisor,
session, discovery, job ownership, interruption, or logging behavior.

## What remains from the refactor

- Supervise each identified meter through startup, jobs, idle time, recovery,
  and removal, using independent continuous journal and health observation.
- Keep network reachability, app readiness, initialization, and job ownership
  distinct. Public readiness also requires journal catchup.
- Check vulnerable UI/navigation/actions synchronously as well as in the
  background, because an update page can beat delivery of its journal signal.
- Return idle/recovered meters to diagnostics when safe to prevent idle sleep.
- Restart an ordinary interrupted subtest after its workers have unwound.
  Retain an already-triggered call-in's original transaction instead of repeating it.
- Preserve optional hardware and existing subtest-specific proof/validation.
- Replay remembered display/results/brightness intent after a meter restart.
- Capture one readable meter-lifetime log, with the compact journal format,
  changed UI/errors, and all job output.

HTTP-to-SSH press fallback remains unchanged apart from lifecycle checkpoints
and the explanatory comment. No press-delivery verification protocol was added.

## What was simplified on November 10

- Removed listener.py, modular monitors, action/watchdog dispatch, and their
  queue/registry dependencies. Subtests already validate their own evidence.
- Removed the added global robot lease and _preparing decorator.
- Kept a single per-meter job reservation. Explicit prepare(meter) callbacks
  run synchronously under it before the worker begins.
- Removed the per-meter admission thread; normal refreshes schedule one
  initialization attempt on the existing discovery pool when ready.
- Restored original serialized scanning, busy-meter tolerance of scan misses,
  and best-effort work-order association.
  Failed supervisor startup removes its partial registry entry so it can retry.
- Restored results-display-before-database insertion, with the production reason
  recorded beside the call order.
- Restored the low-level write_results_json helper. High-level result intent/
  defer behavior is explicit in SSHMeter._apply_display_results.
- Reused SSHMeter's existing inventory caches instead of tracking duplicate
  inventory freshness state. A retry never forces another enumeration.
- Removed unused bookkeeping; retained existing age-based log cleanup for the
  station's SD-card space constraint.
- Restored original call-in elapsed-time calculations; shared recovery deadlines
  remain monotonic. Existing subtest delays and proof rules remain.
- Added concise normal phase/reason messages and suppressed uptime-only
  lifecycle publications. Detailed samples remain controlled by debug settings.

## Interruption and recovery policy

Config writes, Rsync, printer downloads, and SELF power-grace messages are
context only. Blocking starts at update/restart commitment, service loss,
unusable UI, or a genuine generation change. Exact Grace period timeout is the
primary sleep marker; exact platformSleep is secondary. A response alone is not
sleep proof. Without explicit sleep, use normal disconnect/removal policy.

Recovery currently requires a live S4_RUNNING app, diagnostics, at least
75 seconds of app runtime, idle clients/CIM, and three stable seconds. After
disruption it requires current-generation diagnostics-entry evidence. These
are current readiness checks, not a guarantee against a later update.

Overall recovery timeout is 300 seconds across chained restarts. Ordinary
subtests allow two restarts within a 900-second cooperative budget. Physical
work aborts/waits for robot readiness and reacquires brightness/Charuco pose
before retry. Paired solar/keypad cleanup finishes before handoff.

Interrupted verdicts remain separate from peripheral failure in metadata.
stop_on_fail=False does not erase unresolved disruption. Cancellation retains
the meter reservation through worker/result cleanup.

Desired display state survives a meter restart, not a station process restart.
Database job insertion follows the result display so an outage cannot prevent
the display attempt.

## Offline checks and hardware limits

Run the focused offline tests and the Windows tester's --check with the
.venv-lifecycle interpreter. See [supervisor.md](supervisor.md#checking-this-change)
for the commands. These checks do not contact a meter or robot.

Offline regression tests cannot prove actual meter timing or physical clearance.
A hardware pilot still needs idle/sleep wake, update during navigation/payment/
paired robot work, chained restarts, cancellation, reconnect/IP reuse, and
result-screen restoration. No live meter/robot actions were performed as part
of this simplification pass.
