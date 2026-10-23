# Map page bug and performance review — 2026-10-23

Scope: the main map at `/`, in a browser and the installed PWA. Changes preserve
full boundary coordinate precision and the existing Esri/WGS-84 basemap.

## Findings and changes

- **Duplicate preparation:** the HTML request built the full geometry/history
  payload even though the browser fetched the same payload separately. The HTML
  now reads sidebar summaries in two queries; full detail still loads through
  the authenticated API.
- **Hidden label overhead:** the production overview created 2,285 zone-label
  DOM elements for 2,508 zone records, then hid them. Labels now attach only at
  the appropriate zoom and within the viewport. Leader lines and ring labels
  use the same approach, and watermark grouping is cached during a map session.
- **Main-thread blocking:** boundaries now render in ordered batches with an
  eight-millisecond work budget, with progress and an opportunity to paint and
  handle input between batches. Group work-order selection uses the complete
  dataset, including boundaries still waiting to render.
- **External startup dependencies:** Leaflet 1.9.4 and Marked 12.0.2 are now
  served locally. Package SHA-512 integrity was verified against their official
  npm metadata, and original licenses and distribution files are included.
  Esri imagery remains an external network dependency.
- **Failure recovery:** zone requests time out and show a retry control instead
  of silently removing the loading indicator. A failed pipeline request shows
  a separate notice without hiding working zone boundaries.
- **Geometry robustness:** empty leading CAD groups, nested rings and invalid
  vertices no longer break other valid boundaries or the whole zone API.
- **Filtering and selection:** raw label records and polygon records now agree
  on patch IDs; unassigned zones do not incorrectly match a selected patch.
  Filter dimming survives label reattachment after panning. The label toggle
  also hides watermarks/ring labels through later zooms. Sidebar selection
  highlights correctly, and popup selection survives hover changes.
- **Smoothing refresh:** changing one zone's smoothing keeps its full popup
  metadata, attention style, label geometry and filter state. Smoothing is
  bounded to the supported 0–3 range; explicit zero opacity is respected.
- **Text handling:** zone names/codes, notes and work-content text are escaped
  before use in map HTML. Quick actions use data attributes rather than inserting
  a zone code into executable JavaScript. Unavailable browser storage no longer
  breaks popup field settings.
- **Backend overhead:** JSON serialization omits redundant whitespace, related
  request zones prefetch only IDs, membership checks use a set, and an unused
  project join is removed. Day-scoped map data uses Django's configured local
  date. Existing authentication and private HTTP cache behavior remain intact.

## Baseline measurements

Two read-only, in-process requests per endpoint on the office WSL server;
these measure server processing, not public network or satellite tile latency.

| Endpoint | Server time, runs 1 / 2 | Queries, runs 1 / 2 | Response bytes | Gzip bytes |
| --- | ---: | ---: | ---: | ---: |
| HTML `/` | 353.4 / 301.5 ms | 32 / 30 | 1,429,005 | 89,723 |
| Zone data | 243.2 / 240.4 ms | 13 / 13 | 8,112,395 | 554,245 |
| Pipeline data | 0.8 / 0.1 ms | 0 / 0 | 573 | 296 |

The baseline boundary digest covers every zone ID and its exact active boundary
coordinates, sorted by ID. It is compared again after deployment to detect any
unintended geometry change.

## Verification

- Full Django suite: 190 tests, 189 passed and one existing CAD fixture skip.
- Fifteen map JavaScript regressions passed, including a 2,508-zone rendering
  case, geometry formats, viewport labels, filters, recovery and smoothing.
- Nine service-worker tests passed; JavaScript syntax, Django checks,
  static-collection dry run, migration drift check and diff whitespace checks passed.
- Browser preview: nested CAD rings, sidebar search/selection, popup rendering,
  deep-zoom labels, label toggle through zoom changes, and PM form entry checked.
- No production records are created or submitted for these checks.

Physical phone frame rates, OS keyboard behavior, GPS and varying outdoor
network conditions remain device acceptance checks. Browser and server results
do not establish one fixed load time for all networks.
