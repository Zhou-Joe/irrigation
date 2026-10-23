# Shared website and PWA UI review — 2026-10-24

Branch: `codex/unified-page-ui`, based on `4f0ace90` (`codex/ai-chat-ui`).

## Result

The shared UI now applies to the website and installed PWA, including the inner
pages and sub-tabs. `page-ui.css` reconciles legacy page styles after their own
stylesheets; it uses the existing system sans font stack and SVG sprite. Titles
are 22 px on desktop and 20 px on phones, section titles 16 px, body text 14 px,
labels and buttons 13 px, and secondary text 12 px. Phone form inputs use 16 px
to avoid focus zoom. Neutral green surfaces, white cards, consistent borders,
spacing, controls, and touch targets replace the separate visual themes.

| Area | Changes checked |
| --- | --- |
| Work reports | All five tabs, follow-up status filters, comments, exports, media icons, and labeled phone records. PM hides unrelated report filters and explains its own task scope. |
| PM / job plans / crews | Primary and secondary tabs, tables, creation and edit forms, material tree icons, and the shared dialog shell. |
| Irrigation data | Rebuilt sidebar density and control layout; matching query, reset, export, view and metric selectors; compact chart summaries; shared legend and empty states; consistent expand/search controls. |
| Statistics / custom reports | Sidebar and report surfaces, filters, chart builder, section headers, export controls, and contained analysis tables. |
| Region management | All five tabs and six section toggles, including SAT; matching SVG chevrons, centered buttons, keyboard activation, expanded-state labels, and a two-column phone toolbar. Grouped zone tables retain readable columns in a contained scroller. |
| Inventory / projects / users | Primary tabs, labeled phone records, long material descriptions and remarks, order detail tables, dialog layout, folder/item icons, and approval controls. |
| Account / workbench / requests | Compact profile information, matching cards and controls, registration styling and field icons, request and weather icons. Login uses the system's deep green, a continuously animated abstract map, and a clear form. |
| Drawing / CAD / API help | Shared typography and surfaces, context menu icons, phone drawing controls, import and field icons, and contained documentation tables. |

The responsive script preserves existing navigation and data handlers. It adds
labels to phone records, correct tab selection semantics, arrow-key focus with
explicit Enter activation, scroll hints, and labels on otherwise unnamed SVG
buttons. Dynamic table enhancement is batched, including asynchronously loaded
inventory and PM records. Existing native CAD tab selection is preserved.

The login page uses a lightweight CSS/SVG background with moving water lines,
soft light and ripples. It has no marketing copy, feature tags or pause control.
The brand caption is two lines: `FOS · Horticulture`, then `v2.0`. System reduced
motion preferences are respected, and background motion stops while the page is
hidden. A vector version of the existing PWA water/leaf mark is shared by login,
registration, the main navigation and the browser favicon; installed-app PNGs
retain the same geometry. Password visibility is keyboard accessible, submitted
forms show progress, and a failed sign-in retains the username but never the
password. The normal Django authentication and CSRF handling are retained.

## Bugs found during the visual checks

1. A duplicate `.collapse-indicator` rule changed `inline-flex` to `inline-block`,
   shifting the old triangle. Removed it and replaced text triangles with native
   buttons using the shared chevron. All six titles have centered controls:
   32 × 32 px on desktop and 44 × 44 px on phones. Only the chevron rotates.
2. Empty patch, region, pipeline and landmark panels lacked the IDs used by their
   toggle handlers. Their empty states now participate in collapse/expand too.
3. Imported multi-ring numeric boundaries could reach drawing label centroid
   calculations as arrays instead of `{lat,lng}`, causing `Invalid LatLng
   object: (NaN, NaN)`. Both drawing tools now use a shared normalizer. Regression
   coverage verifies finite centroids, unchanged coordinates, and no input mutation.
4. The offline page referenced different stylesheet versions from the worker's
   precache. Versions now match exactly and a Django regression test enforces it.
   The new shared stylesheet is included in the public offline shell.

## Validation

- Django core suite: **198 tests, 197 passed and 1 skipped**.
- Public PWA tests after the final asset version change: **6 passed**.
- Node tests: **43 passed**, including map rendering, location feedback, PWA
  navigation, offline cache policy, and AI streaming/artifact regressions.
- **40 routes rendered successfully**, each loading the shared stylesheet.
- **124 rendered inline scripts and 5 changed external scripts** passed syntax checks.
- Browser checks: **40 routes × 5 viewports** (320 × 740, 390 × 844,
  768 × 1024, 844 × 390, 1366 × 900). No page-level horizontal overflow,
  uncontained controls outside the viewport, or new console errors were found.
  Intentional table/tab/map scrollers were checked separately from page overflow.
- A further 40-route phone pass checked for remaining visible pictographic UI
  text and missing SVG symbols: none found. User-entered business text is retained.
- Manually exercised all settings sections, mouse and Enter activation, group
  collapse, primary tabs, repair follow-up sub-tabs, tab keyboard focus/activation,
  PM creation dialog, and purchase-order creation/cancellation and detail expansion.
- Verified login password visibility with keyboard input and an intentionally
  invalid local sign-in: the error is visible and the submit button is usable
  again. Final login layouts include the requested two-line caption, no removed
  marketing copy, no pause button, and no missing SVG symbols or horizontal overflow.
- Measured all six region-management icons on phone and desktop: centered within
  their buttons and their titles (rounding error below 0.001 px).
- Static collection dry-run and `git diff --check` passed. Normal development
  `manage.py check` reports two existing relative filesystem-cache location warnings;
  the isolated test cache configuration has no system-check issues.

These are browser viewport checks, not a claim of testing every physical phone.
Some fixture sections are empty, and no production business mutations were made.
Screenshots and detailed browser metrics remain local under `docs/reviews/assets/`
and `.tmp-pm-review/`; they are deliberately excluded from this commit.

## Deployment handoff

Local previews use disposable data on ports 8774/8775. The AI preview is explicitly
synthetic; it does not configure a live model. No production deployment was made.
GLM can integrate this branch, collect static assets and restart the application
using the existing production workflow. There are no schema changes or migrations.

Public shell version: `irrigation-shell-20261024-4`; shared CSS/JS version:
`20261024pages4`; login CSS/JS version: `20261024auth4`; region controls stylesheet:
`20261024controls`. Installed clients
receive the normal update prompt and can choose **更新并重新打开** after saving work.
Authenticated pages, API responses and media remain outside the worker cache.
