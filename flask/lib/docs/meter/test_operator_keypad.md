# Operator Keypad Test Notes

`flask/lib/automation/tests/test_operator_keypad.py` is the operator-assisted
keypad validation used by `operator_cycle_all`.

It is intentionally independent from the robot keypad test. The operator test
does not start robot programs, consume robot events, match robot attempts to
meter timestamps, or perform robot retries. Its only proof source is the
meter's own platform journal while a person physically presses the keys.

## Pass Condition

The test passes when every unique normalized button in `buttons` has produced
at least `job_count` accepted `KEY_PRESSED` journal entries.

An accepted entry must:

1. Be newer than the journal cursor captured immediately before keypad-page navigation.
2. Match `KEY_PRESSED: <key>, isAutoRepeat=<value>, from <source>`.
3. Have `isAutoRepeat=false`.
4. Come from `KEY_PAD_2` or `KBD_CONTROLLER`.
5. Name one of the requested buttons.

Button names are stripped, uppercased, de-duplicated in their original order,
and empty names are discarded. An empty resulting list is an input error.

## Flow

1. Validate and normalize kwargs.
2. Start the overall duration timer.
3. Capture the latest opaque journald cursor for
   `MS3_Platform.service` so existing key activity cannot count.
4. Navigate with `meter.goto_keypad()` and verify
   `Service:Utilities:Peripherals:Keyboard` through `UIPage.php`.
5. Poll `journalctl --after-cursor=<cursor> -o json`. Synthetic navigation
   presses are rejected because their source is not a physical keypad source.
6. Parse complete batches atomically, filter keypad entries, and advance the
   cursor to the final entry in each successfully parsed batch.
7. Increment accepted per-button counts and broadcast aggregate progress plus
   the current count mapping.
8. Return successfully when every requested count is satisfied, or fail when
   `max_duration_s` expires.
9. Always store the compact final test state in
   `shared.device_meta["keypad"]`, including when an unexpected exception
   interrupts the test. Journal diagnostics remain in the job log.

Transient journal command and parsing errors are recorded and retried. The
last good cursor is not advanced after a failed read, preventing data loss. If
journal access remains unavailable until the overall timeout, the terminal
failure identifies journal acquisition rather than claiming that a physical
button failed.

## Broadcasts

The normal `progress` event reports accepted required presses as
`current / total`. The `operator_keypad` event additionally contains:

- `counts`
- `required_per_button`
- `missing`
- `current`
- `total`

The custom event is available for a future keypad-specific frontend display;
clients that do not handle it safely ignore it.

## Metadata

`shared.device_meta["keypad"]` contains only the compact final status, error,
requested buttons, required count, confirmed counts, missing counts, and
runtime. Journal cursors and acquisition statistics are not stored in
`device_meta`.

Detailed accepted and ignored press records are written one record per line to
the job log during the test's `finally` block and are not stored in
`device_meta`. Ignored records are bounded in memory by `debug_entry_limit`
before being written to the log.

## Kwargs

- `buttons` (required): button names to validate.
- `job_count` (default `1`): required accepted presses per button.
- `max_duration_s` (default `300`): overall navigation and test timeout.
- `poll_s` (default `1.0`): incremental journal polling interval.
- `page_timeout_s` (default `3`): keypad page verification HTTP timeout.
- `debug_keypad` (default `False`): log ignored key records.
- `debug_entry_limit` (default `500`): maximum ignored records retained.
- `subtest` (default `False`): indicates invocation by a grouped runner.

Keep this document synchronized with material behavior changes in
`test_operator_keypad.py`.
