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
