# Operator NFC Tap Test

`test_operator_nfc_tap` is the monitor-free, operator-guided contactless-card
test used by the `contactless` step of `operator_cycle_all`. It navigates to the
meter's Contact(less) diagnostics page, starts the NFC reader, and waits for the
meter UI to display the masked card number.

Keep this document synchronized with material changes to
`flask/lib/automation/tests/test_operator_nfc_tap.py`.

## Evidence and result rule

The diagnostics UI is authoritative for a successful read. Current production
MS3 meters display a completed transaction as:

```text
emv card read: XXXX XXXX XXXX 0078
```

The final four numeric digits are retained. Each non-`0000` result counts once
for the reader activation that produced it. The same physical card may therefore
be tapped repeatedly when `job_count` is greater than one. Repeated last-four
values are not deduplicated.

The supplied MS3 captures also show this result after a reader cycle in which no
card was presented:

```text
emv card read: XXXX XXXX XXXX 0000
```

`0000` is classified as a no-card timeout. It is logged as a retry, does not
advance progress, and causes the test to re-arm the reader while time remains.

Both `emv card read:` and `nfc card read:` are accepted case-insensitively. The
page title must end in one of the normalized Contact(less), Contactless,
Contactless EMV, or NFC aliases before the test will send a reader command.

## Reader lifecycle

The test captures the newest `MS3_Platform.service` journal cursor before
calling `meter.goto_nfc()`. Each poll reads at most 600 entries after the last
good cursor. It recognizes power replies from both supported modules:

| Module | On reply | Off reply |
| --- | --- | --- |
| `KIOSK_NFC` | `01 00` | `00 00` |
| `KIOSK_NEO` | `01 01 00 00` | `01 00 00 00` |

Power replies, display messages, and transaction result states are diagnostic
evidence. The masked result in the HTML remains the counting authority because
it is the source of the requested last four digits.

An activation begins only when the contactless page is verified, no prior
attempt is waiting for its delayed result, and the reader is off. Pressing
`plus` immediately changes the local state to `turning_on`; journal replies then
confirm `on` and `off`. An off reply does not complete an attempt because the
captures show that the HTML result may arrive several seconds later.

If the page changes during an active attempt, that attempt becomes a retry. The
test returns through `meter.goto_nfc()`, verifies the page, presses `minus`, and
allows the legacy three-second NFC off interval to settle before re-arming.
This avoids sending `plus` while an old activation may still be shutting down.

Transient UI and journal errors are logged and retried. A failed journal batch
does not move the cursor. The overall test fails if the requested reads are not
collected before `max_duration_s`, if a stop is requested, or if setup,
navigation, or another unexpected operation fails.

## Progress and configuration

The test broadcasts generic progress with program `operator_nfc_tap` at zero,
after every successful read, and during finalization. This occurs in standalone
and grouped operator runs.

| Argument | Default | Purpose |
| --- | ---: | --- |
| `job_count` | `1` | Number of successful tap cycles required |
| `max_duration_s` | `60.0` | Overall time allowed, including setup |
| `poll_s` | `0.75` | Delay between journal and UI polls |
| `subtest` | `False` | Records whether the grouped operator runner invoked the test |

The operator settings builder sets `job_count` to zero when the meter has
neither `KIOSK_NFC` nor `KIOSK_NEO`, causing `operator_cycle_all` to report the
step as `n/a`. The existing program aliases and job metadata mapping use the
`contactless` device key.

## Cleanup, metadata, and diagnostics

The `finally` block always obtains and verifies the contactless page before
pressing `minus`. If another diagnostics page is active, it navigates back first.
A cleanup failure changes an otherwise successful result to failure. When a
primary exception already exists, that exception is preserved and the cleanup
failure is appended to the stored error.

Compact results are stored under `shared.device_meta["contactless"]`:

- `result`, `error`, and `elapsed_time`;
- `total_card_reads`;
- ordered `card_last4s`;
- cleanup attempted, success, and error fields.

The job log retains every attempt and its retry reason, relevant journal events,
reader transitions, UI and journal error counts, initial/current cursors, final
reader state, and cleanup outcome. Raw journal traffic and full UI HTML are not
stored in shared metadata.

## Flow

1. Validate arguments, initialize run state, and broadcast zero progress.
2. Capture a journal cursor, navigate to Contact(less), verify it, and save the
   initial HTML.
3. Press `plus` and poll journal plus UI without issuing another activation.
4. Count a non-`0000` result or record `0000` as a retry.
5. Repeat until `job_count` reads pass or the overall timeout/stop ends the run.
6. Verify or restore the contactless page and press `minus` in `finally`.
7. Write compact metadata, detailed logs, and the final progress broadcast.
