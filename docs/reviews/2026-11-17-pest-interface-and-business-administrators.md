# Pest interface and business administrators

The pest workspace now shares the irrigation map bounds, regional watermark
names, work-order weather header and complete user-management page. Account
administration has an explicit business scope instead of relying on a global
Django staff flag to authorize every workspace.

## Resulting behavior

1. Both maps use the same center, rectangular bounds, zoom range (15–22), and
   drag constraints. Pest map watermarks use the same Land names, centers, white
   treatment and font scaling as irrigation. GPS positions outside the park do
   not move the map outside its permitted area.
2. Direction labels are Chinese while stored direction codes and imported
   source snapshots remain intact. Historical English direction labels also
   render in Chinese.
3. Selecting a terminal work item under bird collision death exposes the
   existing collision observation form and a prompt. The server derives those
   related fields from the issued catalogue, validates them, and retains the
   actual selected work item. Bird names/codes remain editable choices;
   reporter and weather remain automatic, with notes in the final remark field.
4. Pest and irrigation details share the weather component and responsive
   header styling. Weather uses the saved snapshot, with the existing same-day
   fallback for ordinary records. Imported history without a weather observation
   shows an explicit missing value rather than today's weather.
5. Record filtering adds a one-year preset and an unbounded all-records option.
   Custom date queries no longer have a 366-day ceiling. Lists, statistics,
   pagination and exports retain the same active team and personal visibility.
6. User management shares the users, approvals, announcements, crews and email
   tabs across businesses. Every account list, including a general
   administrator's view, contains only general administrators and that
   business's staff. Membership-only accounts are included and duplicate
   attribution profiles do not produce duplicate people.
7. Existing global administrator accounts receive an explicit general scope.
   General administrators may restrict themselves or another administrator to
   an active business. Restricted administrators cannot promote their scope,
   modify general/other-business accounts, access system administration or
   bypass scope through the worker API. Scope takes precedence over retained
   Django superuser flags. Registration can request a business-specific manager,
   and approval enforces that business.

## Persistence and related functions

- `operations.0012` adds administrator grants and seeds current administrator
  accounts as general. `core.0146` adds nullable team ownership to announcements,
  crews and mail configurations, crew locations, and registration scope.
- Existing announcement, crew and email rows keep null ownership, which
  represents their original irrigation workspace. No existing work-order,
  location, network, membership or user flag is rewritten by these migrations.
- Business crews use their own members and visible places. Mail report
  attachments are generated from the configuration's owning team. Shared mail
  credentials and global account-mail defaults remain general-admin functions;
  business administrators can maintain their own delivery profiles.
- Notification delivery and acknowledgments use the active business, including
  the landscaping shell. Its user-management functions are available while
  other unfinished landscaping pages retain their existing behavior.

## Validation

- 319 Django regressions pass (one existing skip), including scope changes,
  cross-business edits, CSRF, approvals, scoped SMTP configuration, team exports,
  terminal collision selections, Chinese directions and multi-year queries.
- 133 JavaScript tests pass, including shared bounds, linked parameter fields,
  map initialization and existing DXF behavior.
- A private browser fixture uses the retained live 216-node pest catalogue,
  24 visible places and centers from 2,364 irrigation zones. All 22 regional
  labels appear. The real path through bird collision, glass collision and
  disposal exposes and saves the full observation form.
- Browser checks cover 390px mobile and desktop layouts, weather at the upper
  right, editable bird text, all/year filters, all five tabs, crew and mail
  configuration saves, and a general administrator restricting itself. User
  lists are checked after switching all three businesses. No actual email is
  sent during validation.

Production deployment rehearses both migrations against a database copy and
compares existing business columns before/after the stopped-service migration.
Only the new scope rows and additive schema/default fields are expected to change.
