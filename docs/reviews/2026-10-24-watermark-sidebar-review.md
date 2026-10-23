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
