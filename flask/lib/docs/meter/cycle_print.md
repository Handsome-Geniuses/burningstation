# Printer cycle test

Implementation: `flask/lib/automation/tests/cycle_print.py`.

`cycle_print` (also registered as `printer`) sends `job_count` test receipts.
`cycle_all` calls the same function for its printer stage. Normal runs do not
register `PrinterMonitor`; the test reads `MS3_Platform.service` journal entries
itself and raises errors through the usual job runner. An explicit `monitors`
override can still register a monitor separately.

## One print attempt

1. Check the shared stop event. On an `ms3` meter, reboot the printer before
   each attempt, retaining the existing jam avoidance step.
2. Read the latest journal cursor **after** rebooting and **before** sending
   `meter.printer_test()`. This excludes old replies and reboot status traffic.
3. Poll `journalctl --after-cursor` in JSON format. Advance the cursor through
   every returned entry, including unrelated entries, so none are replayed.
4. Apply the result rules below. Polling and stop checks continue until the
   request watch expires or the attempt can advance.

| Journal event | Pass/fail decision |
| --- | --- |
| `IPSBusDevSendPrintMessageVA` | Start a watch for a result (eight seconds by default). |
| `PRINT_TICKET_REPLY: ... result=SUCCEEDED` after a request | Cancel the watch; the monitor's success condition is met. |
| `PRINT_TICKET_REPLY: ... result=PENDING` after a request | Fail immediately. |
| Any other result after a request | Cancel the watch without a fault, as `PrinterMonitor` did. |
| No result after a request within the watch period | Fail on timeout. |
| No request line | No watch is armed; the fallback wait ends without a monitor fault. |
| `PRINTER_STATUS_REPLY` | No pass/fail decision. |

The last two non-failing cases and the treatment of unknown results intentionally
match `PrinterMonitor`. Do not classify a status flag, a missing request, or an
unknown result as a failure without changing the agreed printer test criteria.

## One eight-second setting

`PRINT_WAIT_S = 8.0` controls both:

- The maximum wait for a result, starting when the print request is observed.
- The fallback wait, starting after `meter.printer_test()` returns.

After a successful result, a **later** `PRINTER_STATUS_REPLY` containing
`TICKET_COMPLETE` and `isCanPrint=true` ends the fallback wait early. This is
only a pacing signal; a missing or unhealthy status does not fail the attempt.
Without that ready signal, the fallback wait uses the same configured duration
(eight seconds by default). If a request has no result, its watch can outlast
the fallback wait and still fail.

`poll_s` defaults to `0.5`. The loop sleeps for at most the remaining watch or
fallback time, then reads the journal **before** checking for timeout. Increasing
`poll_s` can delay detection, but does not subtract from the watch duration.
The watch begins when polling observes the request, so actual elapsed time can
also include up to one poll interval and the journal command's runtime.

The optional `wait_s` argument changes both uses together and cannot reduce
them below eight seconds. The old `timeout_s` and `delay` arguments are accepted
as aliases for this one setting; if multiple names are supplied, their values
must agree. For example, a `cycle_all` printer configuration can include:

```json
{"printer": {"job_count": 3, "wait_s": 8, "poll_s": 0.5, "debug": true}}
```

## Failures and logs

`PENDING`, an expired request watch, a journal read/parse error, or an exception
from the meter command raises out of the subtest. The standalone runner records
the error and fails the job. In `cycle_all`, the printer device result becomes
`fail`; `stop_on_fail` determines whether the remaining stages run. A stop event
also interrupts polling.

Normal subtest logs include the cycle number, observed request and result with
their cursors, and whether readiness or the fallback wait ended the attempt.
`debug=True` additionally logs the initial cursor, each poll's entry count and
starting cursor, parsed printer status, and matched request/result/status
message text. These use `shared.log` and appear in the job log when logging is
enabled. The general listener may separately log raw meter journal lines even
when printer debug is off. The test does not save a separate structured printer
trace in `device_meta`.

Focused tests: run `python -m unittest tests.test_cycle_print` from `flask`.
