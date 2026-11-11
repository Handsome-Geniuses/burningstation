# Meter log search signatures

This page records useful signatures for searching archived meter logs under
`flask/logs`. These are meter-runtime messages, so they can appear in any test
whose listener is still running when the meter emits them.

## Diagnostics-card insertion

Use this processed meter summary as the primary one-result-per-read search:

```text
inferred cardType=15:DIAGNOSTICS
```

A complete matching line resembles:

```text
Meter:sProcessIPSBusMessage: EMV_CONTACT:CARD_READ_DATA: fwVersion=26 CardInfoType=1, ReadType=2:MSR, EncryptionType=0, inferred cardType=15:DIAGNOSTICS cardHash=254762006 isCardAccepted=true
```

The important part is the inferred type, not the example hash. A hash can help
correlate repeated use of the same card, but another valid diagnostics card can
have a different hash.

To see the insertion, processed read, and resulting diagnostics entry together,
enable regular-expression search and use:

```regex
CARD_READ_INST.*D=00 01 01 FF|inferred cardType=15:DIAGNOSTICS|DiagnosticsEnter: ENTER DIAGS
```

The normal sequence is:

1. `CARD_READ_INST ... D=00 01 01 FF`
2. `CARD_READ_INST: ... Flags=STATE_INSERTED`
3. `CARD_READ_DATA: ... inferred cardType=15:DIAGNOSTICS`
4. `Diagnostics:DiagnosticsEnter: ENTER DIAGS`
5. `CARD_READ_INST ... D=00 00 00 FF` and/or a card-removed event

`00 01 01 FF` means a `PREPARE` instruction with the inserted flag. It proves
that the contact reader reported an insertion, but it does not identify the
card by itself. The processed `cardType=15:DIAGNOSTICS` summary is the strongest
single signature for the diagnostics-card use described here.

For a broader search covering every processed contact-card read, regardless of
card type, use:

```text
EMV_CONTACT:CARD_READ_DATA
```

### Searching in VS Code

Open workspace search with `Ctrl+Shift+F` and use:

- search text: `inferred cardType=15:DIAGNOSTICS`
- files to include: `flask/logs/**/*.log`
- files to exclude when investigating the October 2026 station event:
  `**/*{12003859,30000269,30001189,30002014}*.log`

The repository ignores `*.log`, so disable VS Code's **Use Exclude Settings and
Ignore Files** option if the search initially returns nothing.

### October 2026 observation

A repository scan performed on 2026-11-11, excluding meters `12003859`,
`30000269`, `30001189`, and `30002014`, found 37 processed diagnostics-card
reads from 2026-10-19 through 2026-10-21:

| Log date | Matching reads |
| --- | ---: |
| 2026-10-19 | 10 |
| 2026-10-20 | 16 |
| 2026-10-21 | 11 |

All 37 matches were in `cycle_all` logs; none were in `physical_cycle_all`
logs. All 37 reported `cardHash=254762006`, which is strong correlation that
the same diagnostics card was used across stations, but the hash alone should
not be treated as the general diagnostics-card signature.

The observed matches occur around the Call In recovery/update portion of
`cycle_all`. For example, the processed diagnostics-card summary is followed
immediately by `DiagnosticsEnter: ENTER DIAGS`, while nearby lines show the
fresh meter runtime and the call-in post-recovery guard. This is consistent
with an operator reinserting a diagnostics card after an update or runtime
restart returned the meter to its normal UI.

This search cannot recover a swipe that happened after the listener and job log
had already ended. A missing match therefore does not prove the operator did
not swipe the card; it only means the interaction was not captured in that log.
Likewise, multiple matches in one file can represent multiple insertions, so
inspect the surrounding timestamps rather than counting files alone.

The automation currently defines `SSHMeter.present_meter_diagnostics_card()`,
but no production test calls it. Consequently, the October matches were not
created by that helper. Re-check its call sites before relying on this statement
for future investigations.

## Related documentation

- `test_operator_card_reader.md` documents the processed card summary and
  `CARD_READ_INST` payload format in detail.
- `cycle_call_in.md` documents why a Call In can be followed by an updater
  restart and a fresh MS3 runtime.
