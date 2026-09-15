# Operator card-reader test

`test_operator_card_reader` is a monitor-free, operator-assisted QA test for the
MS3 contact magnetic-stripe reader. It moves the meter into diagnostics, captures
a journal cursor, and considers only new `MS3_Platform.service` messages emitted
after that point.

The operator inserts and removes QA test cards until the requested number of
successful reads has been collected. `job_count` is the number of successful
reads required, not the maximum number of physical attempts. A read classified
as retry does not end the test; the operator may try again until `max_duration_s`
is reached.

## Result rules

A candidate exists only when the meter emits its processed summary in this form:

```text
Meter:sProcessIPSBusMessage: EMV_CONTACT:CARD_READ_DATA: fwVersion=26 CardInfoType=1, ReadType=1:MAGSTRIPE, EncryptionType=0, inferred cardType=3:MASTER cardHash=... isCardAccepted=true
```

A processed read counts as a pass when all of these are true:

- `CardInfoType` is `1`.
- `ReadType` is `1:MAGSTRIPE`.
- `EncryptionType` is `0`.
- The inferred type is neither `INVALID` nor `UNKNOWN` (and is not numeric type
  `0` or `1`).
- `cardHash` is not `2147815457`.
- When `require_card_accepted=True`, `isCardAccepted` is also `true`.

The default is `require_card_accepted=False`. That keeps the hardware/read test
independent of meter card-acceptance configuration while still recording the
value. Enable the option when the QA setup also needs to verify that its test
cards are accepted by the active meter configuration.

If a processed read does not meet those rules, it is recorded as `retry`, with
specific reasons, and the test continues. There is deliberately no hard-coded
expected card hash because operators may use different approved test cards.

The test result is a failure only when an unexpected exception occurs, journal
acquisition fails, the automation stop event is raised, or `max_duration_s`
expires before `job_count` successful reads. The absence of an `EMV_CONTACT`
module message and a card that appears to remain inserted are not separate
failure classifications; in practice, no qualifying read simply leads to the
overall timeout.

## Empty Track 2 hash

`cardHash=2147815457` is hexadecimal `0x80051021`. In the archived MS3 source,
`HashCard()` returns that initial CRC combination when its Track 2 input length
is zero. It is therefore a reliable marker for the observed empty-Track-2 read
and is classified as retry.

This direct hash check is preferable to waiting for a later `Invalid expiration
month` message. The expiration message is recorded when present for diagnostics,
but it does not determine the result. This avoids timing-based association and
still catches the empty reads seen in the captured meter logs.

## `CARD_READ_INST` payloads

The archived MS3 `HostInterface.h` defines the four payload bytes as:

```text
Version  Instruction  Flags  Spare
```

The commonly observed values decode as follows:

| Payload | Meaning |
| --- | --- |
| `00 01 01 FF` | version 0, `PREPARE`, card inserted |
| `00 01 41 FF` | version 0, `PREPARE`, card inserted plus magnetic read error |
| `00 00 00 FF` | version 0, `STATUS`, not inserted, no flags |
| `00 00 40 FF` | version 0, `STATUS`, not inserted plus magnetic read error |

The flag byte is a bit field: `0x01` inserted, `0x02` chip data, `0x04`
magstripe data, `0x08` disabled, `0x10` insertion error, `0x20` chip error,
`0x40` magnetic error, and `0x80` abort error.

These messages are decoded, logged, and retained as best-effort diagnostic
context. They never decide pass, retry, or failure. Real captures included a
successful processed read without a later removal/status event, so requiring an
insert/remove pair would create false failures. Their `related_read_number`
field is only a chronological hint. The final event also contains
`related_read_classification`, which shows whether that numbered read became a
`pass` or `retry` (`pending` means no processed read was captured for it).

## Logging and metadata

Every processed read is logged with its classification, reasons, inferred card
type, hash, and `isCardAccepted` value. The complete processed meter summary is
also retained because QA may need it to re-validate or debug a result. Decoded
`CARD_READ_INST` events and expiration diagnostics are retained separately.

The raw IPSBus `CARD_READ_DATA D=...` payload is never stored by this test. The
shared journal listener also filters that specific raw payload line so it cannot
be written to the job log through the parallel listener. It does not filter the
processed meter summary.

Final information is stored under `shared.device_meta["card_reader"]`, including:

- status, error, and duration;
- `classifications`, containing only the ordered `pass`/`retry` classification
  for each processed attempt.

Detailed processed reads, decoded instruction events, diagnostic events, journal
cursors, and polling statistics are intentionally kept out of `device_meta`.
They remain in the card-reader-specific test log entries for troubleshooting.

The test's `finally` block writes the read, instruction, and diagnostic lists in
one `final collected data` log entry instead of emitting one line per list item.
This includes partial results when the test stops or fails. Search that line for
`related_read_number` and `related_read_classification` to see which
`CARD_READ_INST` event was associated with which pass/retry attempt.

## Keyword arguments

| Argument | Default | Purpose |
| --- | ---: | --- |
| `job_count` | `1` | Number of successful reads required |
| `max_duration_s` | `60.0` | Overall time allowed, including diagnostics setup |
| `poll_s` | `0.5` | Delay between journal polls |
| `require_card_accepted` | `False` | Whether `isCardAccepted=false` makes a read retry |
| `subtest` | `False` | Suppresses this test's standalone progress broadcasts |

## Flow

1. Initialize settings, monotonic start time, and run-state storage.
2. Check the shared stop event and call `meter.force_diagnostics()`.
3. Capture the most recent journal cursor after diagnostics is entered.
4. Poll only entries after that cursor, advancing it only after a complete batch
   parses and is processed successfully.
5. Decode and log instruction events; classify only processed card summaries.
6. Pass once the number of successful summaries reaches `job_count`; otherwise
   continue through retry reads until timeout, stop, or an unexpected error.
7. Always write final logs and `shared.device_meta` in `finally`.
