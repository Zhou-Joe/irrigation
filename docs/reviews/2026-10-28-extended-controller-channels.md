# Extended irrigation controller channels

The runtime pivot previously created exactly 24 rows for every satellite. The
production controller `SAT6-7 (40stn, 6-8)` has 40 configured station channels,
so channels 25–40 were imported but omitted from the web matrix, its totals and
the Excel/PDF runtime reports. In the inspected production data this affected
4,072 Actual Log readings totaling 33,424 minutes across the retained history.

## Verified source identity

This grouping was checked against original `SITE_CF`, `CTROL_CF` and `STATN_CF`
records in the retained MDB backup, and against all 40 current production station
records. Controller **58** references internal Site key **6**, which resolves to
displayed Site **6**, named `6 Fantasyland406`. Every station channel 1–40
references controller 58 and internal Site key 6. Every corresponding production
station has the same source/controller/channel metadata and parent CCU6. The
name text `6-8` is not used as proof of Site ownership or to invent a second CCU.

## Behavior and validation

The shared matrix now retains its normal 24 rows and includes any additional
positive configured/recorded channels. A sparse set avoids allocating phantom
rows up to an arbitrary large channel number. Existing controller and Site
membership, station IDs, readings and timestamps are unchanged. The PDF sizes
its table to the actual row count; Excel and both server/client web renderers
use the same complete matrix. Legends no longer claim all controllers have
24 channels.

The full core suite passed 302 tests with one existing fixture skip. Added
regressions cover nonzero channels 25/40 in all/single-CCU results and Excel,
configured channels in an empty query window, and successful PDF rendering.
A generated 40-row PDF was checked for one-page output, extracted channel 40
and minute totals, and visually inspected after PNG rendering. All 40 rows
fit without clipping. The earlier LR37-4 and operator runtime examples pass.

## Production release

Deployed `30cab35b` from `10fdc4f3`. The office GitHub fetch timed out, so the
already-pushed Git commit was transferred as a verified incremental bundle over
the existing authorized SSH tunnel. The bundle SHA-256 was
`8432b1bd70523cb5356b73142a055285405dc236e89bc3aaf4d2d52b5b10494f`.

Read-only checks against consistent production snapshots before and after the
restart confirm all 40 per-channel web and Excel values match the stored Actual
Log sums. The complete matrix totals 21,283,420 minutes, exactly matching the
stored runtime total, including the previously hidden 33,424 minutes. A full
PDF export succeeds, LR37-4 remains in CCU14, and the snapshot file hashes stay
unchanged by verification. No import, migration or business-data write occurred.

Django checks passed, `horticulture` is active on the deployed revision, the
public login returns HTTP 200, and production has no tracked modifications.
Source/database backups, the source-membership audit, release bundle and
candidate/live reports are retained under
`deployment_backups/ccu6-extended-20261028/` (the source audit is retained with
the prior LR release in `deployment_backups/ccu14-lr-20261028/`).
