# Maxicom runtime and time-window review — 2026-10-25

Production uses `import_maxicom_mdb_linux` through `maxicom_nightly.sh` at 08:30
and 16:30. `/home/projects/irrigation` resolves to `/home/noname/irrigation`.
The last completed import was 2026-10-24 16:30, from `MC2Backup10242026.zip`.
Its runtime range was `20250830000037`…`20261023231636` (359,362 rows).
The production settings are `TIME_ZONE=Asia/Shanghai`, `USE_TZ=True`.

A consistent read-only production snapshot and original MDB backups are retained
under `/home/noname/irrigation/deployment_backups/maxicom-review-20261025-004202`.
The review downloaded the 2026-08-29, 09-04 and 10-24 backup archives from the
existing authorized SMB integration. The audit did not run the importer against
the live database. Credentials were neither committed nor included in reports.

## Reconciliation

The operator confirmed the Rain Bird figures are **Actual Log only** and supplied
these local Shanghai-time windows and totals:

| Window | Expected actual runtime in minutes |
| --- | --- |
| 2026-09-02 06:54:00 → 09-03 06:54:59 | 7-3-19=20; 7-4-24=821; 7-6-24=852; 7-8-16=15; other CCU7 stations empty |
| 2026-08-27 07:01:00 → 08-28 07:01:59 | 2-2-21=20; 2-3-15=32; 2-5-2=20; **2-5-23=1500**; 2-6-11=168; 2-6-15=84; 2-6-19=25; 2-6-20=20; 2-6-21=30 |
| 2026-08-18 07:01:00 → 08-19 06:57:59 | 44-3-1=30; 44-3-2=30; 44-3-4=10; 44-3-20=10; 44-3-21=15; 44-3-23=633; 44-4-24=817 |

The operator separately confirmed the initially omitted 2-5-23 value is 1500.
It must be retained, not hidden or capped because it exceeds one calendar day.

All **20 values** match the production snapshot after converting local query
boundaries to UTC. Without conversion, five values differ: 7-4-24=803 instead of
821; 2-5-23=1451 instead of 1500; 2-6-11=108 instead of 168; 2-6-15=42 instead of
84; 44-4-24=818 instead of 817. This is a query-window error, not missing minutes
that should be patched into station totals.

## Confirmed problems and changes

- `MaxicomRuntime.timestamp` contains raw UTC compact **strings**. Django's
  timezone setting cannot transform a `CharField`. The old application compared
  local UI strings directly with these UTC strings. Common helpers now convert
  local bounds to UTC and stored UTC values to local display labels. Original
  log timestamps remain unchanged. Web matrix, heatmap, Excel/PDF, daily AI data,
  weekly reports, data-span hints and latest-valve timestamps share this logic.
- The importer merged `XA_RuntimeProject` with actual `XA_LOG` M readings. The
  former is projected data: the 09-04 MDB contains projected timestamps through
  09-07 and 37 stations with positive projections in the CCU7 example versus
  four actual stations. Actual Log ingestion now uses station `S` / `M` readings
  only. A failed source export rolls back runtime replacement; an empty result
  cannot erase an existing runtime history. Flow export failures preserve the
  prior daily flow records and fail the job.
- UTC flow readings now receive their irrigation-day label after local-time
  conversion. Complete-day flow queries select the actual day labels rather
  than both the previous and selected date. Arbitrary hourly windows explicitly
  explain that precise meter totals cannot be recovered from daily-only storage.
  This prevents complete-day water totals being presented as exact hourly values.

Station controller/channel metadata matched the current active records in both
the 08-29 and 10-24 source snapshots for the sampled stations; the 09-04 audit
found no active-station controller/channel mismatches across the current set.

Rain Bird distinguishes Actual Log from Projected Data in its own manual:
[Maxicom2 manual, section 7.9](https://rainbirdservices.com/wp-content/uploads/2018/10/Maxicom2-Manual.pdf),
[addendum, page 53](https://rainbirdservices.com/wp-content/uploads/2018/10/Maxicom2-User-Manual-Addendum.pdf).
These documents support keeping actual and projected figures separate; they do
not document MDB timestamp encoding. The UTC conclusion comes from the three
independent operator examples and original stored readings.

## Separate water-meter attribution concern

Source Site numbers are not geographic CCU numbers. Production controllers map
source Site 4 to CCU7, Site 7 to CCU8, Site 8 to CCU9, etc. Source Site 12 contains
controllers assigned to both CCU14 and CCU37. The existing flow importer attaches
flow meters by the unconverted numeric Site ID. Precise geographic meter-volume
allocation therefore needs a reviewed mapping, especially shared sites. Runtime
reconciliation does not establish that existing per-CCU meter/estimate sums match
Rain Bird water-volume reports. No allocation ratios are invented by this fix.

## Validation

15 new tests cover all operator totals through web and Excel, heatmap consistency,
inclusive seconds, year/day boundaries, invalid input, local latest-run labels,
full-day meter selection, actual-only import, failed-export preservation and
second-precision values surviving the actual datetime input's initial render.
The complete Django core suite passed: **219 tests, 218 passed, one existing skip**.
The subsequent datetime-control follow-up passed all 15 targeted tests.

The isolated production-copy import also passed all three original-data cases
through the web matrix and Excel; PDF generation succeeded for each window.
Runtime changed from 359,362 rows / 20,428,089 minutes to 356,281 actual rows /
20,417,398 minutes. Flow day labels changed from 17,896 to 17,932 rows; the total
193,445,205 liters was exactly preserved. SHA-256 comparisons of every row in
Zone, Patch, User, WorkReport, WorkReportEntry, GeneratedWorkOrder,
MaintenancePlan, InventoryTransaction and InventoryTransactionLine were unchanged.
The source and candidate database, logs, expected values and checks are retained
inside the private audit directory. Three rendered inline scripts passed Node
syntax checks. Final live deployment verification follows.
