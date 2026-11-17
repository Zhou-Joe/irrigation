# Shared irrigation scope, synchronization window and balanced map colors

The irrigation table now uses one CCU navigator for runtime minutes, actual
sensor liters and FLO WATCH reference records. Independent source-Site dropdowns
are removed. Source **display numbers** match CCU codes: CCU3 selects displayed
Site 3 (internal source key 5), not internal key 3. Original source identities and
water/runtime calculations remain intact. Records lacking a configured CCU remain
accessible under the shared “其他站点” chip.

Navigation initializes on the first rendered page using small CCU metadata rather
than refetching or embedding duplicate matrix cells. Paging updates all tables and
summary cards together; blank CCUs show an explicit empty state. Query responses
are sequenced so a stale request cannot replace a newer scope. Changing a chip
also updates the main CCU selector used by subsequent queries and map views.
On phones the chips scroll horizontally and remain available near the water
section. Switching to the table closes the overlaid filter panel; its reopen
button remains accessible. Water tables wrap names/status so liters stay visible.

The default window ends at the latest successful `DataImportRun.finished_at` and
starts exactly 24 hours earlier, in Shanghai time. A newer failed/running import
cannot advance this anchor. Before the first recorded successful import, the
latest runtime record is the fallback, or current time on an empty installation.
Explicit operator windows retain their previous inclusive second precision.
The “同步前24h” action asks the server for the latest default again, including a
sync completed since the page opened. The resulting exact window is shared with
the map. Both clients preserve an end second of 00 when native inputs omit it;
the map previously expanded such minute-only end values through second 59.

Boundary-less zones retain their real runtime/depth in the unmapped list and
runtime table. They are not drawn without geometry. A defect where their depth
affected the drawn map's volume maximum is corrected; both maxima now describe
drawn zones. The map also honors the selected CCU using actual station membership.

Automatic coloring uses continuous empirical percentile midranks of positive
values from drawn zones. Tied values receive equal colors; zeros, null depth,
unmapped zones and nonfinite inputs do not distort the positive distribution.
This distributes ordinary values across the palette even when one or two values
are extreme. No measurement is clipped or rewritten: tooltips, lists, exports
and displayed maxima retain real values. The legend states the relative color
meaning, median and maximum. Existing manual limits retain linear coloring.

Validation: 294 Django tests passed with one existing CAD fixture skip; 69 Node
tests passed. New regressions cover sync/failure/fallback windows, exact bounds,
CCU display-key swaps, retained unassociated sources, CCU map membership, unmapped
maxima, outliers, ties, zeros, missing depth and manual color caps. Actual rendered
scripts pass syntax checks. Browser checks use disposable synthetic records:
CCU3/CCU5 selection and requery, current sync reset, retained Site 99, a 10-zone
outlier color example and a 320-pixel phone layout. No importer, business records,
email schedules or sensor conversion factors are changed. No migration is needed.

## Production verification

Deployed `1bfdead2` from `49ecf260` after an isolated, read-only production-copy
check. That check preserved the database file hash and confirmed the exact window
`20261026163020` through `20261027163020`, matching the latest successful import.
It retained 2,247 drawn zones and 206 boundary-less zones; CCU3's map contained 172
drawn zones and its sensor source retained internal key 5 / display number 3.
Both map maxima matched drawn observations only.

Django checks, static collection and the `horticulture` restart succeeded. The
public page was checked for the new default inputs, balanced color legend,
coverage counts and CCU3's three physical sensors under the common navigator.
All three served JavaScript files were checked against their deployed source
hashes. Current backup coverage is earlier than the successful import's finish
time; the existing partial-coverage notice remains visible for that default
window, rather than treating uncovered hours as confirmed zero readings.

Private source/database backups, the candidate report and release logs are kept
in `deployment_backups/irrigation-scope-20261028/` on the office server. No schema
update, source-data import or business write was performed during this release.

Final phone follow-up `41b12225` keeps two-digit sensor channel numbers on one
line at 320 pixels. The actual phone fixture confirms both channel 15 and its
liter value remain readable without horizontal scrolling; the production service
was restarted on this final code revision after checks passed.
