# Registration, map sidebar and watermark follow-up — 2026-10-24

Follow-up to `6442e83d` on `codex/unified-page-ui`. The user requested production
deployment after reviewing the local previews; deployment results are recorded
separately below when verified.

## Registration and map sidebar

The general form rule had replaced registration's left icon padding. Registration
inputs and selects now reserve 44 px at the left, with a centered 20 px SVG at
14 px. The narrow component override is intentional: it wins over legacy generic
form selectors without changing other forms. There is about 10 px between the
icon's right edge and the start of the input text. The submit button and footer
also use the shared style and `FOS · Horticulture` / `v2.0` caption.

The main map's region sidebar now has the same white header, neutral surface,
thin borders, type sizes and green controls as the reporting sidebars. Counts,
region/name groups, zone records, search and hover states use the same palette.
The old search-field separator is replaced with a shared search SVG. The orphan
group no longer applies an unrelated inline dark background. The floating reopen
button is 44 × 44 px. Mobile map navigation continues to use its existing controls.

## Watermark choice and replacement

Primary references checked:

- [Ant Design Watermark](https://ant.design/components/watermark/): configurable
  multiline text, rotation, spacing, and modal inheritance for interactive pages.
- [Meta Watermark Anything](https://github.com/facebookresearch/watermark-anything):
  learned localized message embedding and decoding in image pixels. This is an
  image-processing pipeline rather than a replacement HTML overlay. The repository
  is archived; it is a research reference, not a newly introduced dependency.

The practical choice for this application is a lightweight enterprise-style
visible watermark. The implementation is framework independent and adds no
React, model runtime, external font, service, or third-party network dependency.
It is not described as an AI forensic watermark or a guarantee against removal.

The previous hard-coded 19–22 px white text, -40° rotation and off-canvas SVG
coordinates are replaced by a shared component:

- Measure and wrap the full existing identity and warning with the actual system
  font; retain all characters and compute the rotated bounds before allocating.
- Draw a small 11–12 px tile at bounded device pixel ratio (1–3), then repeat it
  in an SVG pattern. The subtle dark fill and light edge work on forms and maps.
- Reuse the tile until the mobile breakpoint or pixel ratio changes. There is no
  animation, polling or per-pan rendering. Personalized pixels stay in the DOM;
  they are not uploaded or stored in the service-worker cache.
- Keep a server SVG with user ID and warning when JavaScript or canvas is unavailable.
  Native dialogs receive their own layer because their top layer bypasses ordinary
  z-index stacking. Fullscreen containers are handled separately.
- Keep overlays inert, hidden from assistive technology and transparent to pointer
  events. The same component covers the two standalone drawing/history templates.
- Repair accidental removal/basic inline style changes with shallow observation;
  this is not a security boundary. A user controlling the browser can still remove
  client-rendered watermarks. Cropping, photographed screens and forensic decoding
  are not claimed to be robustly handled by this visible implementation.

During verification, the native dialog's generic SVG rule initially shrank its
watermark to 24 × 24 px. The watermark now has its own scoped SVG class; the full
380 × 844 px layer was measured and visually checked inside the phone launcher.

The PWA update banner also now clears when another tab has already activated the
update, avoiding a stale prompt whose button would otherwise do nothing.

## Validation and handoff

- Django core: **202 tests, 201 passed and 1 skipped**.
- Node: **48 passed**, including five new watermark geometry/Unicode/DPI cases.
- Four new Django cases cover anonymous/empty identity omission, escaped identity
  attributes, and the non-JavaScript identity/warning fallback.
- All 40 audited routes render successfully. A new **80-page browser pass** at
  320 × 740 and 1366 × 900 found no page overflow, clipped controls, missing
  authenticated watermark canvases, or new console errors.
- Registration: all eight fields, including conditional department fields, checked
  at 320 × 740, 390 × 844, 768 × 1024, 844 × 390 and 1366 × 900. Each has 44 px
  left padding, about 10 px icon/text separation, and vertical alignment within
  0.01 px rounding tolerance. No registration was submitted.
- Region grouping, name grouping, search, collapse and reopen were exercised.
  The reopened sidebar measured 300 px; its floating control measured 44 × 44 px.
- The native launcher remained operable through its inherited watermark. Anonymous
  registration/login and the offline help page contain no personal watermark.
- Static collection dry-run and whitespace checks passed. Local screenshots and
  detailed browser measurements remain outside the commit.

No schema changes are required. Collect static files and restart using the normal
deployment workflow. Public shell: `irrigation-shell-20261024-6`; shared CSS/JS:
`20261024pages6`; watermark CSS/JS: `20261024wm2`; PWA UI script: `20261024update`.

## Production deployment — 2026-10-24

Deployed release `0eb9280c2726703619c09cf75861ad05762b0d84` to
<https://irrigation.zctestbench.asia/> at the user's explicit request. This release
also includes the AI chat and full-page UI changes in `4f0ace90` and `6442e83d`.
The office checkout's `main` branch advanced directly from `9dce1e8e` without
conflicts or tracked local modifications. No database migration was required.

The initial GitHub fetch stalled. A Git bundle with the same reviewed commits
was transferred over the authorized SSH tunnel; its SHA-256 matched at both ends.
After the user restored connectivity, another GitHub fetch succeeded and its
`FETCH_HEAD` exactly matched the deployed commit.

Backup: `/home/noname/irrigation/deployment_backups/ui-release-20261024-030239`.
It contains the previous source archive, commit/status records, a private copy of
the existing environment, and a consistent SQLite online-backup snapshot. The
live database, media, user privileges and production configuration were preserved.

Production Django checks passed with no issues. Static collection copied 18
changed assets; `horticulture` restarted at 03:04:02 CST and remained active with
zero automatic restarts. Subsequent service logs contained no application
tracebacks, internal server errors, worker failures or error-level entries.

Public HTTPS verification returned HTTP 200 for 13 runtime assets and the login,
registration, offline, manifest and service-worker routes. All 13 downloaded
assets exactly matched the deployed source bytes. The public worker contains
`irrigation-shell-20261024-6`; the gateway also confirmed public HTTPS availability.

Read-only browser verification used the existing signed-in production admin
session. The map rendered all 2,508 areas, the loading indicator cleared, and the
AI conversation panel opened successfully without sending a model request.
Work reports, region settings, irrigation data, inventory, PM, profile and the
workbench passed desktop layout checks; phone checks additionally covered
registration. No viewport overflow or clipped controls were found, all protected
pages received the new watermark, and registration inputs retained 44 px icon
padding with a centered brand mark. No new JavaScript errors occurred during
post-restart checks. An initial browser request made before restart encountered
incomplete old static responses during replacement; fresh post-restart loads and
the public byte comparisons confirmed those responses were resolved.

The final targeted watermark/PWA rerun passed all 17 tests. Physical-phone GPS,
camera, keyboard and live-model/tool calls were not exercised during deployment.
No production work orders, PM tasks, users or inventory records were submitted.
