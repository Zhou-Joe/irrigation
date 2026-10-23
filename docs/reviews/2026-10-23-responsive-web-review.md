# Responsive website review — 2026-10-23

Scope: the regular website and installed PWA share the same responsive layouts.
The system sans-serif type scale and compact spacing from the previous release
remain in use. Business logic, permissions and database records are unchanged.

## Problems corrected

- Navigation labels wrapped into multiple lines at tablet/small laptop widths.
  Keep the three primary destinations and expose every module through the
  searchable all-functions menu below 1280px.
- Region toolbar actions extended beyond narrow screens. Actions now use a
  compact two-column grid on phones, while section headers can wrap.
- The boundary DXF importer retained a 340px sidebar on a 360px viewport,
  leaving its map about 6px wide. Drawing/import tools now stack a usable map
  above their controls on narrow screens.
- Chart grids had fixed 450–500px minimum columns. They now adapt to the actual
  available panel width, including presentation mode and reporting sidebars.
- Long form rows, maintenance-note inputs and nested inventory layouts could
  clip controls. Form fields now shrink and reflow; tree detail panels stack
  on smaller screens and stop scrolling under the header.
- Some data tables extended into clipped page content. Shared enhancements
  retain table semantics and all columns, add contained horizontal scrolling,
  display a hint only when needed and support keyboard focus. Late-loaded
  tables and hidden panels receive the same treatment.
- Project dialogs had a viewport-sized minimum height plus outer padding.
  Dialogs now fit the visible viewport; project headers and footers remain
  accessible while their contents scroll. The PM dialog was checked in
  portrait, landscape and desktop layouts.
- Maintenance text and work-content paths now wrap instead of losing detail
  behind an ellipsis. Wide report lists use two columns; expanded reports use
  the full row. Wide admin workspaces can grow to 1680px.
- Sticky actions, toasts and editor footers clear the phone navigation bar.
  Project work-hour values remain available on the narrowest card layout.
- The live PM data exposed a long category list and cramped table columns.
  Phone categories now scroll in one row, while PM tables retain a readable
  760px minimum width inside their own scrolling region. Modal sizing also
  reserves device safe-area insets.

## Browser verification

37 routes × 7 viewports = 259 route/viewport checks in a disposable database.
Viewport sizes: 320×740, 390×844, 768×1024, 1024×768, 1366×768,
1920×1080 and 844×390 (landscape).

| Area | Routes checked |
| --- | --- |
| Main navigation | Workbench, map, all-functions launcher |
| Work orders | Report list, PM, follow-up and media tabs; detail; tree form; legacy form |
| Operations | Water requests, inventory, projects, user management, registration approval |
| PM | Management, new PM plan, Job Plan template, crew form |
| Assets | Region settings; zone, pipeline, patch, region and landmark forms |
| Mapping tools | Quick draw, batch draw, zone DXF import, map-style editor, pipeline CAD import |
| Reporting | Statistics, custom charts, irrigation data |
| Account/help | Profile, login, registration, offline help, API documentation |

Final checks found no controls extending beyond the viewport outside intentional
scrolling regions, and no error pages or captured JavaScript console errors.
The boundary importer map measured 306px wide at a 320px viewport and 377px at
390px. The tablet all-functions menu exposed all role-authorized modules.
Project-create and PM-completion dialogs were inspected without submitting.

Automated validation: full Django suite, 182 tests (181 passed, one existing
CAD fixture skip); nine service-worker tests passed; JavaScript syntax and
`git diff --check` passed. Static collection dry run passed.

Browser viewport checks do not replace testing an actual iPhone/Android
keyboard, camera, GPS, OS download handling or home-screen installation.
Native-device acceptance remains a manual check.

## Deployment

The release uses source checksum guards, a backup of affected files and atomic
file replacement before static collection and the application restart. No
migrations, FRP configuration changes or business-data writes are required.

Deployed to `https://irrigation.zctestbench.asia/`. Production Django checks and
static collection passed, and `horticulture` was active after restart. Public
stylesheet/script, manifest, worker and offline-help URLs returned HTTP 200.
The service worker uses public-shell version `irrigation-shell-20261023-3`.
All nine deployed runtime sources matched the final local checksums; the two
public responsive assets also matched the reviewed source bytes after restart.

Production verification used the existing signed-in admin session and read-only
navigation: real report cards (collapsed and expanded), PM categories/table,
region settings, inventory, projects/create dialog, users, statistics, custom
charts, irrigation data and boundary import. No production records were created
or submitted. No JavaScript errors were captured during those checks.

Backups on the office server:

- `/home/noname/irrigation/deployment_backups/responsive-web-20261023-194510`
- `/home/noname/irrigation/deployment_backups/responsive-polish-20261023-195237`
- `/home/noname/irrigation/deployment_backups/responsive-safeareas-20261023-195529`

Screenshots: [desktop](assets/responsive-web-production-desktop.png),
[phone reports](assets/responsive-web-production-phone.png),
[phone PM](assets/responsive-web-production-pm-phone.png).
