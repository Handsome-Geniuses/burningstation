# NFC cycle test

Implementation: `flask/lib/automation/tests/cycle_nfc.py`.

`cycle_nfc` (also registered as `nfc`) toggles the diagnostic NFC reader ON
and OFF for `job_count` cycles. `cycle_all` calls the same function for its NFC
stage. These flows do not register `NFCMonitor`: the subtest reads the
`MS3_Platform.service` journal itself. The obsolete `test_robot_nfc_read`
test has been removed, leaving no registered test with a default monitor.

## Flow and timing

1. Wait one second, then navigate to the NFC diagnostic page. Navigation can
   send an NFC OFF request; the old test suppressed the monitor during it.
2. Capture the latest journal cursor **after** navigation. This excludes its
   OFF traffic and earlier replies. Poll for the following one-second settling
   period, matching when the old test first enabled the monitor.
3. For each cycle, press `plus`, poll throughout the ON dwell, press `minus`,
   and poll throughout the OFF dwell. The cursor advances through every journal
   entry, including unrelated entries, so lines are not replayed.
4. Keep each ON and OFF phase for at least seven seconds, as the old subtest
   did. A reply cancels its watch but does **not** shorten the dwell. The dwell
   is part of the power cycle, not just a wait for confirmation.
5. Poll for one more second with watches active, clear them, wait one second,
   and return to diagnostics. On an exception during a cycle, attempt to power
   down the reader and return to diagnostics while preserving the original
   error.

The default `poll_s` is `0.5`. Each poll reads all entries after the last
cursor. A watch begins when its request line is observed. Polling first reads
and processes replies, then checks watch deadlines, so a reply at the timeout
boundary is not lost because of the poll interval. A later poll or slow SSH
read can delay timeout detection; it does not shorten the configured watch.

## Monitor-equivalent decisions

| Journal line | Effect |
| --- | --- |
| `GENERIC_TERMINAL -> KIOSK_NFC/NEO EMV_POWER`, payload starting `01 01` | Arm or replace ON watch (6 seconds by default). |
| Same request with payload starting `01 00` | Arm or replace OFF watch (3 seconds by default). |
| `CARD_READ_INST` request with payload starting `00 02` | Arm or replace ON watch. |
| `CARD_READ_INST` request with payload starting `00 05` | Arm or replace OFF watch. |
| Two-byte `EMV_POWER_REPLY` payload `01 00` | Cancel ON watch. |
| Two-byte `EMV_POWER_REPLY` payload `00 00` | Cancel OFF watch. |
| Four-or-more-byte reply beginning `01 01` | Cancel ON watch. |
| Four-or-more-byte reply beginning `01 00` | Cancel OFF watch. |
| Reply for the opposite direction, unknown payload, or `EMV_UI_OUTPUT` | Do not cancel the pending watch. |
| A watched ON/OFF request without its matching reply | Fail when that direction's watch expires. |
| No recognized request | No watch or monitor fault is created. |

An ON and an OFF watch can coexist; the matching reply cancels only its own
direction. A new request for the same direction replaces that direction's
watch. Watches carry between dwells until they are cancelled, expire, or are
cleared during normal cleanup. The test does not require a reply if no
recognized request was logged, because the monitor did not require one either.

`delay` controls each phase's minimum dwell and is clamped to at least seven
seconds. `timeout_on_s` and `timeout_off_s` default to six and three seconds,
matching the former monitor registration. `poll_s` must be positive.

For example, a `cycle_all` NFC configuration may include:

```json
{"nfc": {"job_count": 3, "poll_s": 0.5, "debug": true}}
```

## Failures and logging

An expired watch or journal read/parse error raises out of the subtest. The
standalone runner records the error and fails the job. In `cycle_all`, NFC is
marked `fail`, and `stop_on_fail` determines whether later stages run. Shared
stop events also interrupt navigation waits and journal polling.

Normal subtest logs include the cycle number, watches armed, and ON/OFF
confirmations. `debug=True` additionally logs the initial cursor, poll counts
and cursors, decoded request/reply payloads, and matched raw journal message
text. These use `shared.log` and appear in the job log when logging is enabled.
The general listener may separately log raw meter lines even when NFC debug is
off. The subtest does not save a structured NFC trace in `device_meta`.

Focused tests: run `python -m unittest tests.test_cycle_nfc` from `flask`.
