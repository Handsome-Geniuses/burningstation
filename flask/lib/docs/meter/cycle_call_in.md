# Call-In Test Notes

`flask\lib\automation\tests\cycle_call_in.py` is the end-to-end modem/server validation for MS3 meters.
It is intentionally different from `flask\lib\automation\tests\cycle_modem.py`.

## What This Test Proves

`cycle_modem.py` proves the modem service can be driven on and off and can
report usable signal data.

`cycle_call_in.py` proves the meter completed the real Call In flow that the
diagnostics UI uses:

1. The test enters `Service > Call In`.
2. It presses `+`.
3. MS3 runs `CIMCallInNow()`.
4. CallInManager requests a connection through ConnectionServer.
5. Once connected, MS3 sends Session Agent `callIn`.
6. The Session Agent responds with `callInResponse`.
7. The session completes and the modem is released.
8. If new content/config is pending, the updater may restart MS3 or RunOnce.

## Why We Trust These Data Sources

The test uses three sources on purpose:

1. `cmd.main.meter:status`
   This is the live runtime truth for:
   - `CIM` state
   - `CS` state
   - `MODEM` state
   - PPP connect/disconnect counters

2. `journalctl -u MS3_Modem.service`
   This is the best compact source for modem proof:
   - connect request
   - disconnect request
   - modem state transitions
   - RSSI / BER signal lines

   We prefer this over pulling a very large platform journal window for modem
   details because it is smaller and more targeted.

3. `journalctl -u MS3_Platform.service`
   This is where the Session Agent and updater evidence lives:
   - `callIn`
   - `callInResponse`
   - Session Manager start/completion
   - rsync / runscript activity
   - updater / restart markers

The platform-journal parser associates the first `callIn` sent after the test's
journal watermark with the `callInResponse` carrying the same `reference`.
This prevents an older response or a later startup/scheduled call-in from being
used to validate the manual request. Session completion is allowed to appear
just after the response because that ordering occurs on real meters.

## Pass Criteria

The test passes when it can prove all of these:

1. A call-in actually started.
2. The modem/connection path was used.
3. Session Agent `callIn` was sent.
4. `callInResponse` was received and was not `result=-1`.
5. Session completion evidence was seen.
6. The modem was released afterward, or updater activity proves the connection
   had already been released before restart logic ran.

The preferred release proof is the final live status snapshot returned by the
cleanup wait. It must show:

- CIM ready (`S1_WAITING_FOR_CALL_TIME` or `S4_SUSPENDED`)
- ConnectionServer terminal (`S5_DISCONNECTED` or `S6_ERROR`)
- modem `S1_IDLE` or `S7_ERROR`
- no named ConnectionServer client still requesting the connection

The clients parser deliberately treats values such as
`(none)<hr>Modem Service:` as `(none)`. Some status responses place the next
HTML section on the same logical line.

PPP counter changes, ordered lifecycle transitions, and modem-journal markers
remain alternate evidence. The cleanup snapshot is important because CIM can
return to ready while `RSYNC` or `RUNSCRIPT` still legitimately owns the
connection. The lifecycle observer returns at that CIM transition, while the
cleanup observer continues until the follow-on client releases and the meter is
actually idle.

The old MS3 source treats both `CS_S5_DISCONNECTED` and `CS_S6_ERROR` as
terminal release states: both clear all connection-needed flags and release
connection power. Therefore a successful call-in that ends at
`CS_S6_ERROR`/modem `S7_ERROR` with no clients is a pass under this test's
end-to-end contract, but it is logged and stored as a teardown warning rather
than presented as a clean shutdown.

Signal data is logged when available, but missing RSSI/BER alone does not fail
an otherwise successful end-to-end call-in.

The old Meter source treats a missing `result` in `callInResponse` as `0`; only
`result=-1` means Session Agent could not connect. The automation follows that
rule and checks `result=-1` on the response matched to the request reference.

## Important Edge Cases

### Meter already calling in

The test waits for a ready/idle state before pressing `+`. This lets boot-time
or fault-driven call-ins finish first instead of racing them.

It also waits for the Call In diagnostics page text to change from
`Wait for the current Call In to complete.` to `Press [+] to Call In.` so we do
not press `+` while the UI is still blocking manual call-in.

### Session Agent follow-on clients

`SESSION_MANAGER`, `RSYNC`, and `RUNSCRIPT` are independent ConnectionServer
clients in the old source. A successful `callInResponse` only returns CIM to
ready; it does not imply those clients have finished. The test therefore does
not fail merely because its lifecycle snapshot still says
`cs=S3_CONNECTED | modem=S4_CONNECTED | clients=RSYNC`. It proceeds to cleanup
and waits for a terminal snapshot.

A run still fails when cleanup/recovery ends with a named client such as
`RSYNC` active and the connection busy. This preserves the real failure seen in
`07-56-22_30004641_cycle_all.log`: that active snapshot is not release proof,
and no independent post-call release source exists in that run. The initial
pre-connection idle state is never allowed to stand in for a later release.

Lifecycle modem-disconnect evidence is ordered: the observer must first see
the modem connected before a later disconnected/error state can set that
proof. This prevents the idle polls immediately after pressing `+` from being
misclassified as post-call-in disconnect evidence.

### Fresh boot or fresh MS3 runtime restart

MS3 has a separate startup call-in path in `assets/ms3/main/MS3.c`.

Important source detail:

- The code currently uses `RESTART_CALLIN_SECS = 60`.
- The nearby comment still says "after 5 minutes", but that comment is stale.

That startup timer calls `CIMCallInNow()`, which only does work when
CallInManager is still in `S1_WAITING_FOR_CALL_TIME`.

This means two things:

1. A startup call-in should not stack on top of an already-started manual
   call-in, because `CIMCallInNow()` is ignored once CIM has already left `S1`.
2. The automation can still race the startup timer if the test starts very
   soon after boot or after an MS3 runtime restart. In that case the test might
   begin just before the startup call-in fires and effectively pre-empt that
   one-shot startup attempt.

To avoid that race, `cycle_call_in.py` now performs a startup guard before the
normal ready/idle pre-check:

1. It estimates how old the current MS3 runtime is from the platform journal.
2. If the runtime is still fresh, it waits until the platform journal shows the
   explicit `startup call-in` marker, or until the guard window expires.
3. It then falls through to the existing ready/idle pre-check, which still
   waits for any active call-in to finish before pressing `+`.
#! I'm not really sure how it will handle if the startup call-in receives and begins an automatic update...

The guard is intentionally based on source-backed behavior and gives extra
cushion. It uses current runtime age first, not only system boot age, because
MS3 can restart within the same Linux boot.

### Call In Manager suspended

The diagnostics page allows manual call-in even when CIM is suspended. The test
treats `CIM S4_SUSPENDED` as a valid ready state for this reason.

### Update or restart after call-in

This is expected on first call-ins after the meter is added to DMS or when new
content/config is available.

The test handles this by:

1. Detecting runtime loss or splash after call-in start.
2. Waiting for the meter runtime to recover.
3. Optionally checking the previous boot's journals if recovery suggests a
   restart happened. #! meter does not support previous boot journals, only current.
4. Holding a post-recovery guard window so the meter can settle before the test
   exits.

The source basis for this is `UpdaterCheckForUpdates()` in `assets/ms3/main/Updater.c`.
Updater logic only runs when the UI is idle and ConnectionServer no longer has
an active connection need, so updater markers are valid evidence that the
connection was already released.

#### Observed example: added-to-DMS meter, manual Call In, then update

The log
`logs/2026-04-28/listen_during_call-in_and_update_20260428_091920-listen_all.log`
shows a useful real case:

1. A manual diagnostics Call In completed.
2. Updater then logged `Installing legacy config` and `Restarting, to use new
   legacy config`.
3. That restart was an MS3 services/runtime restart via `systemctl restart
   MS3.target`, not a full Linux reboot.
4. After restart, MS3 came back through `Loading.html`, then normal idle/home
   UI activity was seen, including `Idle.jpg`.
5. Later diagnostics key presses re-entered diagnostics, so the meter did not
   appear to remain parked on `Services > Call In` by itself.
6. About 60 seconds after the restarted runtime came up, MS3 logged the
   explicit `startup call-in` marker and began another call-in through the
   normal CallInManager path.

So for this scenario, the practical takeaway is:

- post-update behavior looked like an MS3 runtime/services restart, not a full
  OS reboot
- the meter appears to have returned to normal idle/home UI before automation
  navigated back into diagnostics
- the restarted runtime did perform another startup call-in

## Key Source References

- `assets/ms3/main/UI/Diagnostics/DiagServiceMenu.c`
  The `+` key on the Call In page calls `CIMCallInNow()`.
- `assets/ms3/main/CallInManager.c`
  CallInManager transitions into connection wait, then sends Session Agent
  `callIn` once connected.
- `assets/ms3/main/Services/ConnectionServer.c`
  ConnectionServer owns connect/disconnect requests to the modem service.
- `assets/ms3/services/modem/modem.c`
  Modem service logs attach/detach requests, state changes, and signal info.
- `assets/ms3/main/Meter.c`
  Meter handles Session Agent notify codes and `callInResponse`.
- `assets/ms3/main/Updater.c`
  Updater may restart the runtime after a successful call-in/update fetch.
- `assets/ms3/main/MS3.c`
  MS3 schedules a startup call-in after runtime startup.

## Result and Metadata Behavior

Each attempt creates `shared.device_meta["call_in"][cycle_number]` before meter
navigation starts and updates it as the attempt advances. Metadata is therefore
available in the job summary on both pass and fail. It includes:

- current status (`running`, `pass`, or `fail`), phase, exception type, and
  elapsed time
- baseline, lifecycle, cleanup, recovery, and effective final snapshots (raw
  status payloads are omitted)
- lifecycle flags and observer errors
- matched Session Agent request/reference/response and session/follow-on
  evidence
- modem journal evidence and signal data
- each validation boolean, the exact proof sources, warnings, and all failure
  reasons

On failure the test emits a compact proof evaluation followed by the complete
per-cycle metadata record before re-raising the exception. In `cycle_all.py`
that exception still marks only the `call in` device result as `fail` and then
propagates through the existing job behavior, so the overall passive result is
unchanged for genuine failures. A pass with a teardown warning remains a
call-in pass and does not change another subtest's result.

## Useful Knobs

The most important kwargs in `cycle_call_in.py` are:

- `ready_timeout_s`
- `ready_stable_s`
- `start_timeout_s`
- `completion_timeout_s`
- `disconnect_timeout_s`
- `recovery_timeout_s`
- `post_recovery_guard_s`
- `post_recovery_timeout_s`
- `status_loss_grace_s`
- `startup_guard_s`
- `state_poll_s`
- `post_completion_grace_s`
- `platform_journal_max_lines`
- `modem_journal_max_lines`
- `startup_platform_journal_max_lines`

If you need tighter journal windows, reduce the journal line counts first
before changing the state-machine timeouts.
