# CCU14 missing LR37-4 runtime column

The source configuration connects controller 213, named `LR37-4`, to internal
Site key 12, displayed Site 14 (Parking lot), through hub 25 / link channel 7.
The importer incorrectly preferred the `37` in its name, assigning the controller,
its 24 station Patches and its runtime records to CCU37. The column was therefore
present in CCU37 instead of CCU14. No Actual Log readings were missing.

The importer now resolves `ControllerSiteNumber` through the current `SITE_CF`
display number first. A descriptive name prefix is retained only as a fallback
when the source Site cannot be resolved. Internal source keys are never equated
directly with displayed CCU numbers. The selected controller configuration is
read once and reused for both station membership and controller rebuilding.

Production metadata showed only one disagreement between current resolved Site
membership and the old name-based grouping: LR37-4. All 1,296 existing runtime
records (17,628 minutes across the retained history) were already imported.
The latest retained LR reading was 2026-10-17 22:21:47 UTC, or October 18 at
06:21:47 Shanghai time. A column without positive values in a recent query is
therefore expected; this repair does not invent recent readings.

There are also 21 configured `14-7-*` landscape zones whose cached station
references were empty because the controller was assigned to CCU37. Those
references must be regenerated after correcting the membership, as in the normal
nightly pipeline. Station IDs, zone identities, measurements and timestamps remain
unchanged. No schema migration or source-data refresh is needed.

Validation: the full Django core suite ran 298 tests, with 297 passed and one
existing CAD-fixture skip. Added regressions cover all 24 LR channels, repair of
an existing station without changing its ID, repeat imports, overlapping link
channel 7 on two different Sites, single/all-CCU web results, Excel cells and
filtered zone heatmaps. Earlier operator runtime examples still pass. The legacy
name-prefix test now checks source-first resolution and unknown-source fallback.

## Production release

Deployed `10fdc4f3` from `41b12225` after validation against an isolated,
consistent production database copy. The repair updated one controller's CCU,
24 station parents, the Site foreign key on 1,296 runtime rows, and the cached
station references on the 21 affected zones. All other columns and tables were
fingerprinted inside the transaction and verified unchanged. No source import,
schema migration, timestamp/measurement edit or email dispatch was performed.

Single/all-CCU application queries and Excel retain the full 17,628 minutes in
the LR column exactly once, under CCU14. The CCU14 heatmap response includes the
21 configured LR zones. Full-history matrix totals were identical before/after
the repair. Django checks and the `horticulture` restart succeeded. Private
source/database snapshots, the repair script and verification reports are kept
in `deployment_backups/ccu14-lr-20261028/` on the office server.

### Separate finding during the total-preservation check

The existing pivot assumes every controller has only 24 channels. Production
`SAT6-7 (40stn, 6-8)` has channels 25–40, so 4,072 stored readings / 33,424 minutes
across the retained history are omitted from the matrix and its exports. Those
readings are retained in the database. This is separate from the LR37-4 Site
membership defect; the follow-up in `2026-10-28-extended-controller-channels.md`
removes the 24-row limit. The LR repair's preservation
comparison uses the same existing matrix coverage before and after, and separately
checks every stored measurement and timestamp remains unchanged.
