# Call-In Test Notes

`cycle_call_in.py` is the end-to-end modem/server validation for MS3 meters.
It is intentionally different from `cycle_modem.py`.

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

## Pass Criteria

The test passes when it can prove all of these:

1. A call-in actually started.
2. The modem/connection path was used.
3. Session Agent `callIn` was sent.
4. `callInResponse` was received and was not `result=-1`.
5. Session completion evidence was seen.
6. The modem was released afterward, or updater activity proves the connection
   had already been released before restart logic ran.

Signal data is logged when available, but missing RSSI/BER alone does not fail
an otherwise successful end-to-end call-in.

## Important Edge Cases

### Meter already calling in

The test waits for a ready/idle state before pressing `+`. This lets boot-time
or fault-driven call-ins finish first instead of racing them.

It also waits for the Call In diagnostics page text to change from
`Wait for the current Call In to complete.` to `Press [+] to Call In.` so we do
not press `+` while the UI is still blocking manual call-in.

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
   restart happened.
4. Holding a post-recovery guard window so the meter can settle before the test
   exits.

The source basis for this is `UpdaterCheckForUpdates()` in `assets/ms3/main/Updater.c`.
Updater logic only runs when the UI is idle and ConnectionServer no longer has
an active connection need, so updater markers are valid evidence that the
connection was already released.

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
- `platform_journal_max_lines`
- `modem_journal_max_lines`

If you need tighter journal windows, reduce the journal line counts first
before changing the state-machine timeouts.
