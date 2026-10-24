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
or static-resource changes are required.

Validation: all 11 dashboard tests passed, including regressions for equipment
and empty areas, a legacy direct station link, inactive/nested areas, and zones
without any patch. The tests use an isolated memory cache to avoid depending on
the development server's filesystem cache.

Production deployment and browser verification are recorded after completion.
