# Field PWA: deployment and phone use

The existing Django site is now installable as **灌溉管理**. Its start page is
`/app/`. This uses the same accounts, permissions, forms and business endpoints
as the website, so there is no second app or data store to maintain.

Production entry point: **https://irrigation.zctestbench.asia/app/** after
deployment. Open that address on the phone before installing. All business
requests use the current website's origin; there is no localhost API server
or separate backend URL to configure in the PWA. An app installed from a local
test address remains attached to that test address. Install from production
to use production accounts and data.

## Production deployment record — 2026-10-23

Deployed to the existing office WSL checkout at `/home/noname/irrigation`
(`/home/projects/irrigation` resolves to the same directory), based on commit
`79d62d24febb5a0adeabc5ff6f9325041c48acad`. The PWA source changes were applied
from the verified release bundle, eight static files were collected, and the
existing `horticulture` service was restarted successfully. No database
migration or business-record mutation was performed.

Original affected source files are backed up on that server at
`/home/noname/irrigation/deployment_backups/pwa-20261023-154738`.

Production verification: `/app/` redirects anonymous users to login with
`next=/app/`; an authenticated workbench render against real production data
returns 200. The manifest, root service worker, offline help, icons and app
assets return 200 through the public HTTPS domain. Worker scope and cache
headers passed, and browser registration reports offline help ready with no
console errors. The production login page is open for the user's manual test.

## Compact UI update — 2026-10-23

The production UI uses a shared native system sans-serif font stack for
English and Chinese, without downloading a display or body font. The scale is
22px desktop / 20px phone page titles, 16px section headings, 14px content and
subheadings, 13px form labels, and 12px captions. Phone inputs remain 16px with
44px targets to retain readable entry and avoid automatic iOS zoom.

Card padding, form spacing, navigation labels and tables are denser. The
workbench places tasks and application shortcuts side by side on wider
screens. At the checked 1270px viewport, the first task moved from about
644px to 393px from the top. Mobile reporting screens now clear the bottom
navigation. The service-worker cache version is `20261023-2` and includes the
shared compact stylesheet for offline help.

Validation: 12 PWA Django tests and 9 worker tests passed; ten module pages,
the workbench, PM form and sign-in page were checked at phone width. The
production app and public stylesheet/worker URLs were checked after deploying
14 reviewed source files, collecting five CSS assets and restarting the
service. The app update action was also verified. Original source is backed
up at `/home/noname/irrigation/deployment_backups/ui-compact-20261023-162258`.

## Included

- Field home with exact pending PM count and the four earliest-deadline tasks
  visible to the current user/crew. Task links open the existing completion
  form, including the saved full-cycle deadline and extension controls.
- Direct shortcuts to work orders, water requests, map and inventory actions.
- Phone bottom navigation and searchable all-functions sheet. Reports,
  irrigation analysis, settings, projects, users, Job Plans and profile remain
  available according to the site's existing role rules.
- Standalone manifest, 192/512px app icons, maskable icon, Apple touch icon,
  platform-specific installation instructions and app shortcuts.
- Safe-area spacing, larger touch controls, readable phone inputs, accessible
  page zoom, native focus-contained dialogs and map/form navigation spacing.
- Connection-loss feedback, guards against offline submission in the main
  field forms, unsent-form exit warnings and explicit app update activation.
- Offline launch/help page; reconnect resumes the originally requested URL.

## Connection behavior

Business operations require a connection: live maps, API data, photos, work
orders, PM completion/extensions, inventory and management changes are not
available offline. Unsubmitted form contents and selected photos remain in
the **currently open page's memory**, not a durable local draft. Do not close
the page or assume they survive an OS app eviction. The UI states this clearly.

The service worker caches only same-origin public `/static/` assets and a
generic offline page. It does not cache authenticated HTML, API results, media,
exports or mutations. It never automatically replays a submission. If the
connection fails after sending, the worker must check the relevant record list
before trying again, because the server may already have accepted it.

The offline help must have been downloaded during an earlier online visit.
If storage is restricted, installation guidance reports that offline help is
unavailable; the live site continues to work.

## Deploy

1. Deploy Django code/templates and static files together using the normal
   release process. No additional database migration is introduced by the PWA.
2. Run `python manage.py collectstatic --noinput` in the server environment,
   and restart the Django application to refresh template caches.
3. Serve the site over HTTPS. Service workers need a secure context (localhost
   is a development exception): [MDN service workers](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers).
4. Route `/service-worker.js`, `/manifest.webmanifest`, `/offline/`, and `/app/`
   to Django. Do not let a proxy rule for all `.js` files intercept the root
   service-worker route. Keep its `Cache-Control: no-cache, no-store,
   must-revalidate` and `Service-Worker-Allowed: /` headers. `/static/` continues
   through the existing static-file server.
5. Check that the manifest returns `application/manifest+json`, the worker
   returns `text/javascript`, and all referenced icons/styles/scripts return
   200 with correct content types. Neither public shell route should redirect
   to login. `/app/` should redirect anonymous users to `/login/?next=/app/`.
6. Open `/app/` on a real Android and iPhone, complete the device checks below,
   then distribute the site's `/app/` URL to workers.

For later releases, bump `CACHE` in `core/templates/core/service-worker.js`
when public shell assets change, and update the asset query versions in the
templates and shell list together. Static requests prefer the network; query
versions are separate cache entries. A new worker waits, displays an update
action, and reloads only when the user chooses it. Dirty forms trigger a
discard confirmation. A work order in flight prevents an update reload.

## Install on phones

- **Android:** open the HTTPS `/app/` URL in Chrome/Edge, sign in, select
  **安装应用** and follow the browser prompt. If the native prompt is unavailable,
  use the browser menu's install/add-to-home-screen option.
- **iPhone:** open the URL in Safari, sign in, tap Share → **添加到主屏幕** → Add.
  Open the new **灌溉管理** home-screen icon. iOS uses a manual installation flow:
  [web.dev installation guide](https://web.dev/learn/pwa/installation).
- In the app, **全部** exposes every permitted module. PM tasks can be started
  from the home page or the work-order PM tab. Existing camera, location and
  file permissions remain controlled by the phone/browser.

## Validation performed

- Django suite: **182 tests, 181 passed, 1 existing CAD-fixture skip**.
  Includes 12 PWA tests for auth, role navigation, exact crew task count,
  deadline order, preview limits, task links, HTML escaping and public routes.
- Node worker tests: **9 passed**. Cover private-data/mutation bypass, offline
  fallback, exact version lookup, HTTP errors/redirects, quota failures,
  explicit updates, cache cleanup and bounded public-asset storage.
- JavaScript syntax, Django system checks, migration consistency and diff
  whitespace checks passed.
- Local browser verification in a disposable fixture database: all 11 main
  modules render at a 390px phone viewport without page-wide horizontal
  overflow. PM completion shows the scheduled/full-month deadline and an
  accessible submit footer. All-functions search, manager navigation and
  installation guidance work. Stopping the test server produced the offline
  help page; restarting and selecting reconnect restored the requested page.

The production deployment above passed server and browser checks. Actual Android/iPhone
home-screen installation, camera/gallery capture, GPS permission, downloads,
software keyboard, landscape and app-switch/resume must still be checked on
the target devices after HTTPS deployment. Browser viewport tests do not
replace those device checks. Push notifications, background submissions and
durable offline drafts are not implemented in this release.

## Commands

From `internal_server/` in the configured Python environment:

```text
python manage.py test core
python manage.py makemigrations --check --dry-run
node --test scripts/tests/pwa-service-worker.test.cjs
node --check static/js/pwa.js
node --check static/js/dashboard-modal.js
```

The original app icon can be regenerated with
`python scripts/generate_pwa_icons.py` (Pillow).
