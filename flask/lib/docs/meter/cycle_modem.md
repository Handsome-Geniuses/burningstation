# Modem cycle test

Implementation: `flask/lib/automation/tests/cycle_modem.py`.

`cycle_modem` (also registered as `modem`) tests modem connection and
disconnection for `job_count` cycles. `cycle_all` runs the same function for
its modem stage. Normal runs no longer register `ModemMonitor`; the subtest
polls `MS3_Platform.service` journal entries with a cursor while its cycle is
active. The separate `ModemMonitor` class remains available for explicit
registration, so keep its request and state patterns aligned with this test.

## Existing subtest checks

The journal watch supplements these existing checks; it does not replace them.

1. Navigate to the call-in page and run the startup call-in guard. The guard
   looks for platform startup and startup call-in markers, and waits through
   the configured startup window when needed.
2. Poll the modem's state before cycling. A busy state can cause a cycle to be
   **skipped** after the precheck timeout, as before. A precheck state read
   error still allows the cycle to proceed.
3. Once ready, capture the latest journal cursor. This is the point where the
   former test enabled `ModemMonitor`; navigation and precheck activity is
   intentionally excluded.
4. Record meter time for the signal lookup, wait the configured lead period,
   and send CONNECT. The state poll must reach `S4_CONNECTED` within its
   configured connect timeout.
5. Require a parseable `csq:` line after the recorded meter time. Its RSSI and
   BER are saved in `shared.device_meta["modem"][cycle_num]`. Missing signal
   information triggers an OFF cleanup attempt and `Modem Connection Error`.
6. Wait five seconds, send DISCONNECT, and poll the modem state until either
   `S1_IDLE` or `S7_ERROR` within the configured disconnect timeout. Wait five
   more seconds before the next cycle.

The existing state wait functions still retry transient state-read errors and
raise on their own timeouts. Errors during a connected cycle still attempt a
modem OFF cleanup before propagating the original error.

## Former monitor rules, now polled locally

The observer reads all JSON journal entries after its current opaque cursor.
It advances the cursor through unrelated lines but only interprets lines
containing `modem`, matching `ModemMonitor.interested()`.

| Journal line | Watch action |
| --- | --- |
| `MODEM: SendRemote: CMD.CONNECT` | Replace any active watch with a CONNECT watch (35 seconds). |
| `MODEM: SendRemote: CMD.DISCONNECT` | Replace any active watch with a DISCONNECT watch (30 seconds). |
| Modem line containing `state=S4_CONNECTED` | Cancel a pending CONNECT watch. |
| Modem line containing `state=S1_IDLE` | Cancel a pending DISCONNECT watch. |
| Other states, including `S7_ERROR` | Do not cancel a watch. |
| An active watch reaches its deadline | Raise a modem failure. |
| No recognized request | No monitor-equivalent watch is armed. |

The monitor's modem-info parsing is commented out, so the observer does not
copy it. The subtest's own `csq:` lookup remains the required signal check.

One intentional distinction remains: the subtest's state poll accepts
`S7_ERROR` as a disconnected state, but the monitor rule only cancels a
DISCONNECT watch on `S1_IDLE`. An `S7_ERROR` can therefore satisfy the state
wait while the journal watch remains active. Whether that watch faults before
the cycle ends depends on its remaining time, matching the previous flow.

The observer is active during the signal lookback lead, connection and
disconnection state waits, and both five-second dwell periods. It is inactive
during startup guard and busy precheck. Its cursor and watch are discarded at
the next cycle's precheck, matching the old allow-list reset.

## Settings and debugging

`poll_s` defaults to `0.5` seconds and controls **journal** polling during an
active cycle. The existing `state_poll_s` (default 2 seconds) and
`precheck_poll_s` (default 3 seconds) remain separate. The journal polling loop
caps sleep by an active watch's remaining time, reads the journal, and then
checks timeout. Polling can delay detection because of SSH command time; it
does not shorten the watch.

The journal watch uses the monitor registration's fixed 35-second CONNECT and
30-second DISCONNECT limits. The configurable `connect_timeout_s` and
`disconnect_timeout_s` still control the subtest's **state** waits. They were
independent of the monitor configuration before this refactor and remain so.

`debug=True` adds the initial cursor, poll counts and cursors, and matched raw
request/state journal messages to `shared.log`. Normal logging records watch
arming and cancellation plus the existing state, signal, and cleanup messages.
The general listener may separately log raw meter lines even when modem debug
is off. Journal read or JSON parse errors now fail the subtest because local
verification cannot proceed without those entries.

Example `cycle_all` configuration:

```json
{"modem": {"job_count": 2, "poll_s": 0.5, "debug": true}}
```

An exception propagates to the standalone runner or `cycle_all`; `cycle_all`
marks modem `fail` and applies `stop_on_fail`. A busy precheck skip remains a
non-failing outcome, as in the original subtest.

Focused tests: run `python -m unittest tests.test_cycle_modem` from `flask`.
