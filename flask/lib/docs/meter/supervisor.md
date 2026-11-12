# Meter supervision: flow and review guide

Keep this document synchronized with meter_manager.py, lifecycle.py,
supervisor.py, jobs.py, runner.py, and guarded SSHMeter operations.
[lifecycle.md](lifecycle.md) is the shorter policy overview.

## Follow a normal meter from connection to results

| Step | Entry point | What happens next |
| --- | --- | --- |
| 1. Scan | METERMANAGER.refresh | The existing IP scanner finishes its probe. The discovery lock serializes scans, as before. One missed scan does not remove a card. |
| 2. Identify | Manager discovery pool → __identify | Connect SSH, read the eight-digit hostname, register an initializing card, and start supervision. Identification has four shared worker slots; it does not wait through boot. |
| 3. Observe startup | Supervisor journal + health threads | Follow the journal continuously and sample live service/runtime/status/UI independently of job SSH. Enter diagnostics when controllable and idle. |
| 4. Initialize once ready | Next refresh → discovery pool → __admit | Reserve the meter, read actual modules/firmwares/region/versions, insert the meter, attempt work-order association, and upload custom display assets in auto mode before admission releases controls. A display upload error is reported but does not reject valid inventory. |
| 5. Admit | __admit → admitted=True | The card becomes eligible for jobs after app readiness and journal catchup. A missing optional peripheral is accepted. Work-order association failure warns without rejecting admission. |
| 6. Prepare/start job | start_passive_job / start_physical_job / start_operator_job → start_job | Reserve this meter, open its job section in the lifetime log, run the explicit prepare(meter) callback once, log options/info, and start the worker. |
| 7. Run | run_test_job → existing cycle or individual subtest | Outer cycles wrap each stage in run_subtest. Standalone tests get that same wrapper in runner.py. Their own proof/verdict code remains responsible for results. |
| 8. Finish | jobs.job_done | Build/log results, update the meter results display, then insert the database job. Display-before-DB is intentional: DB errors have occurred in production. |
| 9. Release | Job worker finally | Flush logs, release this meter after cleanup/result handling, publish status, and then call the existing auto coordinator. Continuous capture stays running. |

The callbacks are ordinary functions called synchronously by start_job before
its worker starts. They return options or None. They replace the hidden
_preparing decorator and do not introduce a second worker or retry preparation
independently. Physical setup keeps its bay check, brightness/display order,
robot event flush, and original five-second post-start clearance delay.

Discovery follow-up: on a mixed LAN, reachable non-meter devices currently
receive repeated SSH identification attempts, eventually every 60 seconds.
Consider a longer cooldown after the initial quick retries. Keep periodic
rechecks so a meter can take over an IP, and reset retry state when the IP
disappears. A fixed exclusion list would not cover changing devices or IPs.

There is no global robot lease or added robot scheduler. Existing station/robot
sequencing remains responsible for resource selection. The small optional
SharedState arguments in RobotClient only make existing waits notice cancellation
or meter interruption.

## Follow an interrupted subtest

1. A late journal marker, unusable application/UI, or genuine generation change
   invalidates the session epoch and signals the current job.
2. A guarded action or ordinary check_stop_event notices it. Navigation stops
   pressing into an update page. A background flag alone cannot win every race.
3. The affected stage unwinds. Paired solar/keypad workers clean up together.
   Physical work requests robot abort and waits for its existing ready status.
4. run_subtest permits supervisor recovery while waiting; the supervisor cannot
   take controls from an active job without this handoff.
5. Recovery obtains a usable current app/diagnostics baseline and restores saved
   display intent/brightness, then verifies another health sample.
6. The wrapper restarts only the interrupted stage, with fresh proof and physical
   pose where needed. Completed earlier stages remain recorded.

An already-triggered call-in is the exception: retain its original watermark and
transaction proof, wait through shared recovery, and continue validation without
another plus press. No modem/send/response/session proof requirement was relaxed.

Ordinary retries allow two restarts within a 900-second cooperative budget.
Recovery has a 300-second deadline, including chained restarts. Exhaustion is
recorded as meter_disruption/interrupted, separate from a peripheral verdict.
stop_on_fail=False cannot clear an unresolved lifecycle disruption. Cancellation
keeps controls reserved until the worker and cleanup finish.

## What the session means

session_for(meter) reads an attribute already stored on the Python object.
It does no network I/O, page read, locking, or waiting. Legacy/mock objects
without a session use their ordinary path.

| Session fact | Meaning |
| --- | --- |
| generation | Linux boot ID + systemd MainPID + service start monotonic time. Missing fields are not a new generation. |
| epoch | Attempt invalidation counter. Sleep/UI loss can change it without a new process. |
| ready | Internal app/recovery readiness. |
| admitted | Initial inventory/database initialization completed. |
| owner | This meter's current operation; prevents supervisor navigation against a job. |
| public snapshot.ready / claim | Also require admission and journal catchup. |
| desired display | Latest requested mode/banner/results/brightness held in this station process. |

The per-meter reservation is retained because supervision can now navigate while
idle. It is not a robot-resource reservation. The original SSH command lock is
also retained. Supervisor observation uses separate SSH clients. Session waits
release their condition while waiting; ordinary network commands are not run
while holding that condition. Inventory's final cache commit checks the epoch
under the condition after navigation is complete.

## Loading and physical identification checks

Settings `flow.load_check` and `flow.physical_check` choose whether to blink a
candidate meter for operator confirmation. They do not change the supervisor's
readiness or control rules. The UI selects meters whose published status is
`ready`; `SSHMeter.blink_until_start()` separately claims the meter session,
and `start_job()` claims it again before physical or passive meter work. An
unready or already owned meter cannot run those guarded commands.

| Situation | Current behavior and follow-up concern |
| --- | --- |
| Meter remains ready | Blink, confirmation, and the later job claim work normally. With either check disabled, an exact bay guess skips blinking, so the guess must identify the correct meter. A missing exact guess still takes the blink path. |
| Candidate becomes unready before blink | The session claim rejects the blink. The UI does not check that `identify_until` succeeded before showing its confirmation dialog. Auto physical confirmation can let `MeterInterrupted` escape its worker rather than retrying. |
| Candidate changes during or just after blink | Guarded brightness writes stop on a lifecycle interruption; recovery is responsible for restoring brightness if that write cannot finish. The UI may still hold a stale candidate. `identify_stop` waits at most two seconds for its thread, so an immediate physical-job claim can be refused while the blink lease is releasing. |
| Candidate becomes unready before confirmation | A physical-job claim rejects a meter that is still unready, although the UI may already report a confirmation. Loading is different: `station.load_L` checks belt sensors, not meter-session readiness, and may move the belt and assign the selected IP as the bay guess. The later passive-job claim cannot undo that move. |

The UI also ignores the station-load response before requesting a passive job
in auto mode. A rejected load can therefore still trigger a passive-job start
attempt; check that response when revisiting this flow.

These are timing and identity gaps in the identification flows, not permission
for meter SSH actions through an update or restart. If these flows are revised,
check the blink request/result, revalidate the selected meter before a station
load, and wait for the blink lease to release before starting a physical job.

## Readiness and actual meter evidence

Current recovery checks are active MS3, live S4_RUNNING runtime, usable UI,
diagnostics, app age at least 75 seconds, no connection clients, CIM S1/S4,
and three stable seconds/quiet after a blocking notice. Following a disruption,
diagnostics-entry journal evidence must belong to the current boot/service.
An HTTP 200 or readable old UI file alone is insufficient.

The 75-second minimum is a policy heuristic inherited from the refactor, extending
the old >70-second admission wait. It is not a guarantee that every peripheral
has appeared or no later update can occur. Countdown values are minimum waits,
not a promised ready ETA.

It also does not prove the current MS3 generation's startup call-in has run.
Archived production runs `2026-10-19/09-47-21_30005988_cycle_all.log`,
`2026-10-19/11-28-28_30005989_cycle_all.log`, and
`2026-10-20/10-05-03_30005980_cycle_all.log` reached `S4_RUNNING`, then show a
quiet interval and a grouped power grace timeout, sleep/wake, timer refresh,
and startup-call-in marker. Old listener timestamps mark workstation receipt,
so they do not resolve exact meter-side timing. See the post-restart sleep section
in `flask/wc_copy/debug production logs/2026-10-20 Various Errors/11-11 Call-In
Update and Reboot/README_FOR_AGENTS.md`. A current-generation, sleep-aware
readiness rule needs validation against meter journal source/monotonic times;
the 75-second gate alone can admit work before a startup call-in is observed.

| Evidence | Treatment |
| --- | --- |
| Exact Grace period timeout / exact platformSleep command | Sleep entry; retain the known meter for wake/recovery. |
| platformSleepResponse, SELF-only power, config writes/Rsync/printer downloads | Context, not an early blocking flag. |
| Legacy-config installation/restart, package/app update commitment, service stop/watchdog | Immediate interruption. |
| Explicit Update/Restart HTML | Immediate interruption in the synchronous read too. |
| One blank UI | One reread after 50 ms; a persistent blank still interrupts. |
| Incomplete health output | One immediate reread; persistent failure is observation loss, not a fabricated PID/start tuple. |
| First missed discovery probe | Keep registration/card. |
| Second miss | Normal idle removal; busy meter is retained without interrupting on ping alone; explicit sleep is retained. |

Descriptions progress through restarting → booting → settling/restoring →
initializing → ready as evidence changes. The last interruption remains separate
from the current waiting description. Recovery timeout shows intervention; the
observation loop continues rather than being forcibly killed.

## Inventory uses the original caches

The supervisor's **generation** identifies one running MS3 instance with a
three-part tuple: Linux boot ID, MS3 Platform MainPID, and that process's
monotonic start timestamp. An MS3 service restart changes the process part;
a Linux reboot also changes the boot ID. An incomplete health sample is not
treated as a new generation. A genuine change clears cached modules, firmware,
region, and versions and requires fresh diagnostics evidence before readiness.
The meter session retains saved display intent across MS3 generations.

The **epoch** is a separate interruption counter. It changes when observed
work is invalidated, including a generation change or explicit sleep/update.
A subtest or admission captures its epoch and checks it before committing a
result. Sleep/wake can change the epoch without changing the MS3 generation.
The meter session ID spans both and ends only at removal.

Initial admission requests get_info(force=True). A genuine generation change
clears hardware/version/region caches. Retrying a subtest calls ordinary
get_info(), reusing an inventory that recovery already read. There is no second
inventory-generation stamp and no forced module walk just because a retry began.

Enumeration accepts the modules actually reported by the IPSBus overview:
printer-less, single-module, and valid empty inventories are allowed. Failed
transport/parse/stuck-page reads are not recorded as missing hardware.

Recovery can enumerate under maintenance authorization before ready. Its cache
commit checks authorization and the pinned epoch, not readiness; requiring ready
there caused the observed circular restoration loop.

## Results and low-level writes

display_utils.write_results_json is restored to its original unconditional
upload behavior. It has no lifecycle lookup or hidden wait/defer branch.

SSHMeter._apply_display_results is the explicit high-level policy: remember the
completed payload for recovery; if the app is unavailable, return without waiting;
otherwise call the original writer and select results mode. Supervisor recovery
replays the remembered payload with the same low-level writer.

Only completed-result intent is saved this way. Generic asset/banner/image writers
retain their existing behavior. A stored UI mode does not reconstruct a payment
transaction or prove a robot pose is valid.

job_done updates the display before insert_meter_jobs. This ordering protects
operator-visible results during a DB outage. An exception still reaches the job's
error/cleanup path; it is not a reason to hide already computed test results.

## Journal, logs, and debugging

The supervisor is the only continuous journal reader. Listener, modular monitors,
their action/watchdog dispatcher, monitor registry, and monitor queues are retired.
Subtests retain their direct journal proof queries.

One file per discovery is written under its start date. A session crossing
midnight keeps writing to that same file:
~~~~text
flask/logs/<YYYY-MM-DD>/<HH-MM-SS>_<hostname>.log
~~~~

The filename uses station-local time; hyphens stand in for colons so it also
works on Windows. If the same hostname starts two sessions within one second,
the later file receives a numeric suffix (_2, _3, etc.) without overwriting
the first. The session ID and IP remain in the file's lifecycle records.

It includes startup, changed raw/rendered HTML and errors, admission decisions,
all jobs/subtests, recovery, and removal. SharedState borrows its writer.
Job completion flushes rather than closing the session. Pre-identity failures
use flask/logs/<YYYY-MM-DD>/discovery.log.

Compact journal lines retain the requested form:
~~~~text
[09:47:28.237] supervisor.journal: MESSAGE | {"__REALTIME_TIMESTAMP":"...","__MONOTONIC_TIMESTAMP":"...","__CURSOR":"..."}
~~~~

Non-Platform entries include their unit; source-change events record boot/PID/
invocation identity. History/live-stream boundary events distinguish backfill.
Raw CARD_READ_DATA payloads are redacted. These other-conversation logging fixes
are retained. Not every original JSON field is repeated on disk.

The locked writer batches roughly 64K characters or two seconds at the next write,
and flushes on monitor polls, finalization, and close. It is not fsync durability.
No lifecycle log is deleted or compressed automatically. Older
flask/logs/meters/<hostname>_<ip>/ folders and dated job-log folders are left
untouched. Compression, if added later, must preserve the full contents and
must not rewrite or remove historical logs. Disk usage still needs to be
observed on the station.

The meter file receives supervisor events and SharedState job/subtest messages.
It is not a capture of process stdout/stderr. Plain prints from the station,
Flask request handling, the Windows tester/Next.js process, and third-party
SSH libraries may appear only in the launching terminal or its process manager.
Check the launcher's Docker logs or explicit terminal capture for those
cross-system details; the Python app does not set up a global terminal file.

Normal terminal output shows phase/reason changes. Elapsed runtime alone no
longer emits another lifecycle row/SSE event. Gate/countdown/owner changes still
publish. Full raw sample/decision context is opt-in:

| Control | Effect |
| --- | --- |
| Settings: meter_monitoring.debug, default false | Live detailed file/terminal decisions. |
| Settings: meter_monitoring.capture_ui, default true | Live changed HTML/error capture. |
| METER_SUPERVISOR_DEBUG / METER_CAPTURE_UI | Explicit environment overrides. |
| Tester --supervisor-debug | Forces the debug environment override. |
| METER_SUPERVISOR_RECOVERY=0 | Supervisor-construction option disabling automatic recovery actions. |

SharedState has no listener/monitor import. end_listener is only a legacy-named
shutdown Event still read by solar/keypad workers; it does not represent a running
listener. Old nonempty monitors kwargs are logged and ignored.

## Checking this change

From flask in PowerShell, use the existing .venv-lifecycle interpreter for
offline checks. These commands do not contact a meter or robot. Run the
keypad-plan tests separately because they install global import stubs.

```powershell
$env:HARDWARE_PROFILE = 'portable'
$env:MOCK = '1'
$python = '..\.venv-lifecycle\Scripts\python.exe'
& $python -m unittest tests.test_meter_initialization_logging tests.test_meter_lifecycle tests.test_meter_job_ownership tests.test_managed_call_in tests.test_meter_wipe tests.test_stop_on_fail tests.test_operator_fail
& $python -m unittest tests.test_cycle_modem tests.test_cycle_nfc tests.test_cycle_print
& $python -m unittest tests.test_mock_passive
& $python -m unittest tests.test_robot_keypad_plan
& $python -m unittest tests.test_operator_keypad_mock.OperatorKeypadMockTests.test_runner_logs_without_the_retired_listener tests.test_operator_keypad_mock.OperatorKeypadMockTests.test_individual_operator_buttons_override_only_job_count
& $python wc_test\windows_passive_and_UI_tester.py --check
```

Restart the Windows tester to load Python and its copied frontend. Its settings
copy is temporary. Runtime timing, real update/sleep chains, robot abort/clearance,
and production firmware menus still require a representative hardware pilot.
