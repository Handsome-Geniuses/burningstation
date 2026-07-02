# Robot Keypad Test Notes

`flask\lib\automation\tests\test_robot_keypad.py` is the end-to-end robot keypad
validation for MS3 diagnostics.

It is intentionally different from the older monitor-driven keypad approach.
The test now owns the robot event handling, journal polling, retries, success,
failure, and metadata directly.

## What This Test Proves

The test passes only when it can prove that:

1. The robot attempted the requested keypad buttons.
2. The meter stayed on or returned to the keypad diagnostics page long enough
   to observe the interaction.
3. The meter's own platform journal produced matching `KEY_PRESSED` evidence
   for each required button press.
4. Retry logic was able to recover from meter-non-confirmed attempts when
   possible, while still logging unrecovered robot-event gaps clearly.

This means the test is validating the real meter-side keypad logs, not only the
robot's idea of what it touched.
If the robot reports `pressed=False` but the meter still logs a real
`KEY_PRESSED`, the test counts that attempt as a success.

## Why We Trust These Data Sources

The test uses two sources on purpose:

1. Robot `button_press` events
   These tell us when the robot started a press, when it reported a final
   outcome, and which button / attempt number the event belongs to.

2. `journalctl -u MS3_Platform.service`
   This is where the meter logs the actual keypad evidence we care about:
   `Meter:sProcessIPSBusMessage: KEY_PRESSED: ...`
   The test also reads and filters `isAutoRepeat=true` so auto-repeat lines are
   never counted as fresh button confirmations.
   It also checks the trailing `from ...` source and only accepts
   `KEY_PAD_2` or `KBD_CONTROLLER`.
   Sources like `ALL_DEVICES` are ignored because they can come from synthetic
   meter-side presses such as `meter.press()` rather than a real physical key
   press.

The robot events tell us which button attempt is in flight.
The journal tells us whether the meter itself observed that key press.

## Current Flow

The high-level flow in `test_robot_keypad.py` is:

1. Normalize the button list and read timing kwargs.
2. Navigate to `Service > Utilities > Peripherals > Keyboard`.
3. Capture an initial **meter journal cursor** from the meter clock with a
   small overlap.
4. Start `run_button_press` on the robot.
5. Start a small collector thread that continuously consumes robot
   `button_press` events and timestamps them when the station receives them.
6. In the main loop:
   - call `check_stop_event(shared)`
   - drain queued robot events into local attempt state
   - poll the meter journal incrementally
   - buffer and match eligible `KEY_PRESSED` lines to pending attempts
   - evaluate per-attempt timeouts and retries
   - start a short grace window on early `program_done`
   - fail on overall `max_duration_s`
   - re-enter the keypad page if the UI drifted
7. When all required meter confirmations are observed, send
   `finish_button_retries` to the robot job so the robot server can close its
   retry acceptance window.
8. Log the full `KeypadRunState` for diagnostics, and write a compact summary
   to `shared.device_meta["keypad"]`.

## Timing Model

### Meter journal cursor / watermark

The journal watermark is **meter-side only**.

It is not based on robot timestamps, and it is not trying to convert robot
times into meter times.

Instead, it is only a scan cursor used to avoid re-reading the entire platform
journal every loop:

1. Right after keypad navigation, the test asks the meter for its current clock
   and subtracts a small overlap.
2. Each journal poll reads from `--since "<current cursor>"`.
3. After the poll, the cursor advances to the newest parsed journal timestamp,
   again with a small overlap.
4. Deduplication prevents the overlap from double-counting the same log line.

So the watermark is just an incremental journal cursor.
It does not try to synchronize robot and meter clocks.

### How robot events and journal lines are related

Robot events and meter logs are related by:

1. normalized button name
2. pending attempt order
3. timeout and eligibility rules

They are **not** related by assuming the robot and meter clocks are in sync.

### Why `short-precise` is used

The current test uses:

`journalctl -u MS3_Platform.service --no-pager -o short-precise`

This is preferred over plain default output because:

1. it is human-readable during debugging
2. it includes sub-second timestamps
3. it is stable enough to parse and dedupe

The earlier JSON approach was useful because it exposed exact structured
timestamps like `__REALTIME_TIMESTAMP`, but it was much harder to read while
watching the test live.

`short-precise` keeps the readability benefit while still giving enough timing
precision for overlap scanning and duplicate suppression.

### After-buffer before matching

After the robot sends `pressed=True`, the test does **not** try to match a
journal line immediately.

Instead, the attempt becomes eligible for normal journal matching only after
`journal_after_buffer_s` has elapsed since the station received that final robot
event.

This gives the meter time to emit the `KEY_PRESSED` journal line before the
test decides that the log is missing.

The same after-buffer idea is also used when the robot reports `pressed=False`.
That case is not treated as an immediate failure anymore.
The test first waits the after-buffer, checks the meter journal, and only then
queues a retry if the meter still did not confirm the press.

The default `journal_after_buffer_s` is currently `3.5` seconds.

## Important Edge Cases

### Robot says `pressed=False`

The test does **not** immediately queue a retry.

Instead it:

1. waits `journal_after_buffer_s`
2. polls the meter journal again
3. counts the attempt as a success if the meter logged a valid
   `KEY_PRESSED`
4. queues a retry only if the meter still did not confirm that button press

When a retry request is accepted, the original attempt is marked as replaced
and removed from pending journal matching. The retry press must then arrive as a
new robot `pressing` event, creating a new pending attempt. Future
`KEY_PRESSED` journal lines for that button are matched to that replacement
attempt, not to the original attempt that triggered the retry.

Retry replacement attempts follow the same normal matching rule as planned
attempts: the robot must send its final `pressed=True` or `pressed=False` event,
then `journal_after_buffer_s` must elapse before a journal line can confirm the
attempt.

### Retry budget with repeated buttons

`max_retries_per_button` is currently a shared retry budget per logical button
name, not per planned press attempt. With `buttons=["1"]`, `job_count=10`, and
`max_retries_per_button=1`, the test expects 10 meter-confirmed presses and can
request at most one retry for button `1` across the whole run.

### Robot sends `pressing` but never sends `pressed`

The test currently just logs this in all caps once the timeout is exceeded.
It does **not** try to recover this case automatically yet.

### Page drift

If the meter is no longer on the keypad page, the test logs that fact and calls
`meter.goto_keypad()` again.

### Early robot completion

If the robot program reaches `program_done` before all required key presses were
confirmed in the meter journal, the test does not fail immediately. It starts a
`robot_program_done_grace_s` window, currently 6.0 seconds by default, and keeps
polling the meter journal during that window. If the remaining required meter
confirmations arrive before the grace expires, the test can still pass. If the
grace expires and the meter confirmations are still incomplete, the test fails.

This grace window is meant to absorb late journal visibility after the robot has
already completed its planned queue. It is not a replacement for retry handling.

### Failure and robot abort ownership

`test_robot_keypad.py` marks the keypad result as failed, sets
`shared.stop_event`, and raises `StopAutomation` when it cannot recover a keypad
failure. It does not directly abort the robot job it started.

Normal physical keypad runs are expected to execute through
`physical_cycle_all.py`. That wrapper catches the failed subtest and sends the
robot `abort_program` command. If `test_robot_keypad.py` is run directly outside
that wrapper, the robot may continue its original `run_button_press` queue after
the station-side test has failed unless the caller sends an abort command.

### Successful completion retry-window finish

When all required button confirmations have been observed in the meter journal,
the test calls the robot `finish_button_retries` command with the active
`job_id` and reason `client confirmed final button registered`. The test does
not inspect the response data; this is a best-effort signal to tell the robot
server that the client has confirmed success and no more retry requests should
be expected.

### Job count and press order

`job_count` means each unique normalized button must be confirmed that many
times. The robot-side `run_button_press` program applies `job_count` by cycling
through the original button list repeatedly, for example:

`PLUS, MINUS, OK, PLUS, MINUS, OK, PLUS, MINUS, OK`

The station-side test validates counts and pending attempt order; it does not
require the robot events to arrive in a separate grouped-by-button order.

## Useful Knobs

The most important kwargs in `test_robot_keypad.py` are:

- `per_button_timeout_s`
- `journal_after_buffer_s`
- `max_retries_per_button`
- `retry_command_timeout_s`
- `max_duration_s`
- `robot_program_done_grace_s`
- `poll_s`
- `debug_keypad`

`poll_s` defaults to 0.5 seconds. It controls the main loop cadence for
processing queued robot events, polling meter logs, checking timeouts, noticing
`program_done`, and recovering from keypad page drift. The robot event collector
thread still polls the robot event queue separately every 0.05 seconds.

If `max_duration_s` is explicitly passed, the test uses that value exactly. If
it is omitted, the default is workload-aware:

`50.0 + (6.0 * len(unique_buttons) * job_count)`

The `6.0` second component is named `per_planned_press_timeout_s` in the code's
default calculation. It covers the planned button presses only, not an expanded
worst-case retry count. Retry behavior is still bounded by `max_retries_per_button`,
`per_button_timeout_s`, `journal_after_buffer_s`, and the overall
`max_duration_s`.

`debug_keypad` is the easiest bring-up switch.
When enabled, the test logs:

- startup config
- meter journal cursor updates
- raw robot event handling
- after-buffer waiting decisions
- journal poll summaries
- retry request / cancel responses
- timeout and retry decisions
- final summary state

If you need to tune behavior, start with:

1. `journal_after_buffer_s` if you want a longer delay before meter-log
   evaluation begins after the robot's final event
2. `per_button_timeout_s` if the overall confirmation window is too short
3. `poll_s` only if the loop cadence itself becomes the bottleneck
