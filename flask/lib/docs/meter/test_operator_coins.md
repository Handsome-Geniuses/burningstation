# Operator Coin Validator Test

`flask/lib/automation/tests/test_operator_coins.py` is the monitor-free,
operator-guided test for the meter's `MK7_VALIDATOR` coin peripheral. It is
available as `test_operator_coins` and `operator_coins`, and runs as the
`coins` device immediately after the screen test in `operator_cycle_all`.

Keep this document synchronized with material changes to the test program.

## Authoritative meter event

The test considers only new `MS3_Platform.service` journal entries after an
opaque cursor captured immediately before `meter.goto_coins()`. A physical
attempt is created only from the meter's processed summary:

```text
Meter:sProcessIPSBusMessage: CURRENCY_ITEM: index=1 type=coin handling:accept location:cashed validationWindow:2 itemIndex:2 configVersion=1 value=5 code='USD'
```

This line is the most complete and reliable result because it contains the
validator disposition, configured item index, signed value, and currency code.
`LAST_COIN` is not used: the MS3 source deliberately ignores it after a
versioned `CURRENCY_ITEM`, and its data is redundant. `sAddCoin` and
`WAddCoin` are also downstream effects rather than the validator report.

Coin indexes are stored in attempt logs for diagnostics, but never identify a
requirement. Indexes depend on the active meter configuration. Requirements
are matched by uppercase ISO currency code and the absolute minor-unit value.
Consequently this test does not use or change
`COIN_VALUE_TO_INDEX_BY_REGION`, which remains the synthetic coin-injection
mapping used by `SSHMeter.insert_coin()`.

## Requirements and defaults

`coin_requirements` is a nonempty mapping whose key is the operator-facing
denomination name:

```python
{
    "euro_20_cent": {
        "currency_code": "EUR",
        "value_minor": 20,
        "quantity": 2,
    }
}
```

Names must be nonempty. Currency codes must contain three letters, values and
quantities must be positive integers, and two names cannot have the same
currency/value identity. `allow_rejected` is a single top-level test kwarg,
not a per-denomination setting. When enabled, it permits matching
`handling:reject` events to satisfy every requirement in the run. A matching
accepted coin always qualifies. Its standalone default is `False`.

When the caller omits `coin_requirements`, these region defaults apply:

| Region | Requirements |
| --- | --- |
| `us` | 3 pennies, 3 nickels, 3 dimes, 3 quarters, 1 dollar coin |
| `uk` | 3 each of GBP 5p, 10p, 20p, and 50p |

The captured US configuration reported a correctly identified penny as
`handling:reject`, `value=-1`, and `code='USD'`. Therefore the grouped operator
cycle enables the run-wide `allow_rejected` option. A standalone caller must
enable it explicitly if rejected-but-identified coins should advance progress.
An unsupported region must supply explicit requirements.

`job_count` is accepted for compatibility with the grouped test runner and
enables/disables the subtest through operator settings. It does not multiply
coin quantities. Values above one are logged as currently unused.

## Counting and pass rules

Every processed `CURRENCY_ITEM` whose type is `coin` is an insertion attempt.
An attempt is a detected denomination when it has both a nonzero signed value
and a nonempty currency code. Unknown rejected events such as `value=0`, an
empty code, and item index 99 remain insertion diagnostics but are not detected
denominations.

For a matched requirement:

- `detected` counts every matching denomination.
- `accepted` and `rejected` count the meter's dispositions.
- `qualified` counts accepted events plus rejected events when the run-wide
  `allow_rejected` option is enabled.
- `credited` counts qualified events only up to the required quantity.

Excess events remain in the actual counters and logs but cannot inflate
progress. The test passes when the sum of credited coins equals the sum of all
required quantities. It fails on timeout, a stop request, setup failure, or an
unexpected error. Transient journal read or JSON errors are logged and retried
without moving the last good cursor. If journal access remains unavailable at
timeout, the failure reports journal acquisition rather than missing coins.

## Broadcasts

The test broadcasts its initial state, every batch containing attempts, and
its final state. The standard `progress` message uses program
`operator_coins` with credited and required totals. The custom
`operator_coins` event contains:

- `ip`, `status`, and `error`;
- the run-wide `allow_rejected` policy;
- `progress_percent` as a fraction from `0.0` through `1.0`;
- `current` and `total`;
- `detections`, with each requirement's identity, policy, and counters.

These broadcasts occur for standalone and grouped runs so an operator display
can always show which denomination is still needed.

## Cleanup, metadata, and diagnostics

The `finally` block always calls `meter.clear_coin_tallies()` before final
metadata and summary logging. The cleanup time is therefore included in the
stored elapsed time. A raised cleanup exception or a `False` return changes the
coin result to failure and prevents `operator_cycle_all` from continuing. If a
primary test error already exists, it remains the raised error while cleanup
details are appended to metadata and runtime logs.

Compact results are stored in `shared.device_meta["coins"]`:

- `result`, `error`, and `elapsed_time` in seconds;
- total inserted, detected, required, and credited counts;
- the run-wide `allow_rejected` policy;
- `detections_dict` with per-requirement counts and configuration;
- cleanup attempted/success/error fields.

The detailed attempt list is kept out of shared metadata. Each attempt is
logged with its insertion and detection number, meter disposition, configured
indexes, matching requirement, eligibility, credited status, requirement
progress, timestamp, cursor, and complete processed summary. Final log entries
also retain the complete attempt list and journal acquisition statistics.

## Lifecycle

1. Start the duration timer and validate settings and requirements.
2. Broadcast zero progress and check the shared stop event.
3. Capture the latest journal cursor, then navigate to the Coins diagnostics
   page.
4. Poll and atomically parse entries after the last good cursor.
5. Record attempts, update requirement counters, and broadcast progress.
6. Finish when every required quantity is credited or fail on timeout/error.
7. Always clear meter coin tallies.
8. Write final metadata and logs, broadcast the final state, and propagate any
   failure so the grouped operator cycle stops.
