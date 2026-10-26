# Actual flow sensors and October 24–25 runtime reconciliation

## Operator report and time distinction

The operator supplied 3-5-1=0 minutes, 3-7-23=895 minutes, sensor 15 Low=2380 L,
16 High=0 L and 17 WP=34200 L for October 24–25, initially described as 03:32 AM.
Read-only production/source inspection reproduced the website's 87 and 881.

Original `MC2Backup10262026.zip` XA_LOG records simultaneously reproduce all five
operator figures for **Shanghai 2026-10-24 15:32:00 → 10-25 15:32:00**:

| Shanghai window | 3-5-1 min | 3-7-23 min | Low L | High L | WP L |
| --- | ---: | ---: | ---: | ---: | ---: |
| October 24 03:32 → October 25 03:32 | 87 | 881 | 4690 | 0 | 33600 |
| October 24 15:32 → October 25 15:32 | 0 | 895 | 2380 | 0 | 34200 |

Station 1397 (3-5-1) has original stamps `20261023210037` (29 min) and
`20261023223737` (58 min), displayed as October 24 05:00:37 and 06:37:37 Shanghai.
These precede the afternoon window and fall inside the morning window. This does
not establish a global timezone defect. Operator confirmation of AM versus PM
remains pending; no global time conversion, runtime rows, station identity or
projection policy changes. The page states the applied Shanghai range in 24-hour
notation.

## Confirmed water-source defect

The previous water repair retained `FLOZO_CF` / `XA_FLOZO` records. These are
**FLO WATCH zones, not the physical sensor channels**. Earlier claims that their
labels represented the requested FS/WD/Toilet sensors were incorrect. Source-zone
identity/precision repairs remain useful for that separate category; matching
XA_FLOZO alone did not validate physical meter readings.

The requested sensors are DCODE_CF indices 82/83/84, source Site internal key 5,
displayed Site 3 Tomorrowland, controller 18, channels 15/16/17. Decoder type 8 is
marked `DecoderTypeFlowMeter=Y`. Actual volumes use XA_LOG **D/F** records:
`SignalValue` pulses × the same reading's `SignalMultiplier`. D/C calibration
events, station minutes, projections and FLO WATCH zones are excluded.

Preferred display units are `Liters`. Source metric calibrations use 3.785
L/source-gallon: 18.49405506278534 → 70 L/pulse; 52.84015732224383 → 200 L/pulse.
Logged factors have fewer decimal places; retain microliters internally and round
only displayed liters, never substituting today's factor for historical logs.
The afternoon window has Low=34 pulses and WP=171, yielding 2380 and 34200 L.
High has no D/F readings in the covered window and displays 0.

[Rain Bird's addendum, page 63](https://rainbirdservices.com/wp-content/uploads/2018/10/Maxicom2-User-Manual-Addendum.pdf)
documents gallons-per-pulse calibration, not MDB timestamps. The installation's
metric factor is supported by its configuration and independent operator values.

## Implementation

- Separate sensor metadata and indexed daily storage; compressed second offsets
  and microliters support arbitrary windows. Full days use SQL sums; only boundary
  days decompress samples.
- `--sensors-only` preserves runtime/FLO WATCH/business tables. Regular/flow-only
  sync includes sensors; sensor failure rolls back the combined flow update.
  Failed/empty/malformed exports preserve prior data.
- Site keys, display numbers and channels stay distinct. Non-flow decoders are
  excluded by type. Disabled/uncovered sensors do not invent zeros. Coverage gaps
  are explicit. Master/submeters are never combined.
- Web/JSON and AI distinguish sensor liters from FLO WATCH reference values.
  AI workspaces export a separate sensor CSV. Weekly reference charts/digests
  honor inclusion flags and stop claiming raw FLO WATCH units are cubic meters.
- A minimal original-data fixture retains 42 station and 62 sensor rows.
  Regressions cover both time windows, five supplied values, identity, dated
  factors, seconds, cache, coverage, disabled sensors, failures, rollback and UI/AI.

## Verification and release

Local full validation: 275 Django tests (274 passed, one existing CAD fixture
skip), 60 Node tests passed; migration drift check passed. An additional combined
flow rollback regression is checked separately. Production-copy validation and
release results will be recorded after completion.

Private source audit: `/home/noname/irrigation/deployment_backups/oct26-window-audit/`.
No credentials are included in this report, fixture or repository.
