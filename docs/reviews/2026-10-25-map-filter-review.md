# Map patch filter — 2026-10-25

The production map filter offered every `Patch` row. This shared table contains
geographic areas/CCUs and imported Maxicom valve stations. Production had 3,377
rows, including 3,352 `station-` records, but only 22 patches were referenced by
the zones displayed on the map. Empty locations and equipment made the filter
unusable and caused thousands of unnecessary chip elements and animation timers.

The dashboard now derives patch IDs from its existing sidebar zone summaries,
queries only those patches, and excludes the canonical `station-` equipment codes
case-insensitively. Only ID, name and code are selected. This preserves custom
and nested geographic areas and keeps inactive areas that still have displayed
zones: four production road patches are inactive but still need to be filterable.
An ordinary area whose human-readable name contains “Station” is preserved.

The change only affects the map's filter options. It does not alter imported
equipment, hierarchy, runtime records, boundaries, or zone assignments. No schema
changes are required.

Live selection testing also found the panel's clear button remained hidden:
JavaScript removed its inline display value but the stylesheet still set
`display: none`. It now toggles the existing `visible` class provided by that
stylesheet. The dashboard script version is `20261025filters`.

Validation: all 11 dashboard tests passed, including regressions for equipment
and empty areas, a legacy direct station link, inactive/nested areas, and zones
without any patch. The tests use an isolated memory cache to avoid depending on
the development server's filesystem cache.

Deployed `47d4bd74` and the clear-action follow-up `9e102b26` through GitHub to the
office production server. Backup:
`/home/noname/irrigation/deployment_backups/map-filter-20261025-003114`.
Django checks passed; one changed static file was collected. `horticulture`
restarted at 00:35:55 CST and remained active with zero automatic restarts and no
warning/error journal entries. The public dashboard script exactly matched its
source SHA-256. The tracked production working tree remained clean.

Production read-only browser checks confirmed 22 area chips and zero station
chips. West gate selected 87 zones; the inactive exploration road selected 92.
Both clear actions restored all 2,508 zones. The clear button appeared only during
an active filter. At 390 px the panel occupied x=12…378 with no document overflow;
desktop and phone screenshots were saved locally. All 2,508 map boundaries
finished loading. Database counts remained 2,508 zones, 3,377 patches and 3,352
station records. All 11 Django dashboard tests and 21 JavaScript map regressions
passed; JavaScript syntax and diff whitespace checks passed. No business records
were submitted during verification.
