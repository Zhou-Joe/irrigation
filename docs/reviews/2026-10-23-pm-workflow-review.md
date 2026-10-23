# Job Plan / PM assignment and work-order workflow review

Reviewed 2026-10-23. Confirmed defects below were repaired in this checkout.
Scope: Job Plan and plan forms, rotation, CCU/SAT/Land crew matching, dispatch,
task lists and notification entry points, both work-order submission paths,
completion edits, photos, materials/project associations, extensions and permissions.

## Findings and repairs

| Priority | Confirmed problem | Result after repair |
|---|---|---|
| P1 | PM notifications still expected the removed `report_id` and opened the ordinary WorkReport editor. The notification button was missing or selected the wrong record type. | Both notification routes use `gwo_id` and open PM completion. Other pages preserve the task ID when navigating home. |
| P1 | Canceling a PM form left its task identity/content available to a subsequent regular form. The map-first path reused the old form DOM. | Closing clears PM identity; a new regular form rebuilds its contents. Browser verification confirmed a regular `#1` was created while the canceled PM remained dispatched. |
| P1 | A task could be completed with missing, replaced or additional zones, or a work date before its scheduled date/in the future. | Both save paths require the issued asset scope and a real execution date between the scheduled date and today. PM asset selection is read-only in the modal. Legacy orders without snapshots use their existing report/plan links. |
| P1 | Raw PM JSON embedded in script tags allowed a Job Plan name to terminate the script element. The dashboard also emitted the same payload ID twice. | Django `json_script` escapes embedded content; each page has one authoritative PM payload. A script-closing name round-trips safely in a regression test. Notification JSON uses the same escaping. |
| P1 | Invalid desktop uploads returned from inside a transaction after creating a PM completion record, leaving an orphan that could block retries. Malformed IDs could fall through to the wrong record type. | Inputs and uploads are validated before writes; invalid/conflicting IDs and PM/ordinary merge combinations return 400. Both paths reject malformed entry/material containers and negative counts. |
| P1 | Photo removal accepted arbitrary submitted paths and could delete files before a later transaction failure. | Only photos belonging to that record can be removed, and deletions run after commit. New PM uploads have a separate directory below `workorder_photos/pm/`. |
| P2 | New PM forms did not prefill their Job Plan/category or offer extensions. Failed seed loads still opened an unseeded form. | Required seed data provides the PM category, Job Plan, scope, scheduled date and saved deadline. Failed loads close cleanly. Work date defaults to the actual current date. |
| P2 | Reopening a PM record replaced its saved description with the Job Plan name and lost entry photos on save. Completed tasks still offered extensions. | Saved text/photos survive edits; missing PM entries are seeded on the server for older clients. Completed tasks have no extension controls. |
| P2 | PM submissions with project-linked entries accessed confirmation fields that exist only on WorkReport, causing the save to fail. | WorkReport confirmation logic runs only for WorkReport owners; PM entries and material ownership remain separate. |
| P2 | Desktop PM completion redirected to a regular WorkReport with the same numeric ID. History showed the assigned leader instead of the actual executor. | Success opens the PM record; completion history uses its actual worker. |
| P2 | An asset without a Patch was assigned the first unrelated CCU. Changing a plan's target also changed the label shown on already-issued tasks. | Missing locations remain null; issued task labels derive from their issued zone scope. |
| P2 | Plan forms retained irrelevant hidden Zone/CCU/SAT links. Automatic assignment counted disabled explicit crews as already assigned. | Each plan stores only the links for its Job Plan's asset level. Disabled crews are reported as unassignable. CCU and SAT crew priority and snapshots are covered by dispatch tests. |
| P2 | Running migrations before WorkItem seeding permanently skipped the PM leaf; a cached missing leaf could survive a later repair. | `seed_work_items` creates/repairs `1.2.pm`, and form metadata reads current reference data. |
| P2 | Old execution dates outside the dropdown's 90-day range were written into a hidden field while a different date remained visible. | An explicit date option is added when needed, keeping the visible and submitted dates consistent. |

## Scheduling and deadline verification

The preceding rotation repair is included in this review. Ten monthly PMs are
spread at three-day intervals in a 30-day cycle. Monthly phases use real cycle
lengths, including leap February; saved phases do not move on daily reruns.
Issued orders retain their dates, status, crew and deadlines during rotation cutover.

Every newly issued monthly order retains a complete calendar month from its
scheduled date to its deadline. Early generation does not shorten that period.
January 31 ends on February 28/29; the deadline day is still on time and the next
day is overdue. Repeated completion, unauthorized access, skipped tasks,
extension approval/cancellation, overdue cleanup and pagination remain covered.

## Verification

- 170 Django tests: 169 passed, one existing CAD test skipped for a missing drawing fixture.
- 85 PM tests in `core.tests_pm` and `core.tests_pm_workflow`, including 20 added workflow regressions.
- Model/migration consistency and JavaScript syntax checks pass.
- Browser checks used a separate loopback-only fixture database: open a PM from notifications, inspect category/Job Plan/deadline, submit actual findings, verify disappearance from pending work, reopen and retain the findings, cancel a PM then submit a regular order, and submit an extension after the original deadline.
- Business PM tables are empty locally. No production database or scheduler was accessed; production data distribution and cron installation were not independently inspected.

## Deployment

Deploy the changed Python/templates/JavaScript, run `python manage.py migrate`
(including `0132_pm_rotation` from the rotation repair), run
`python manage.py collectstatic --noinput`, and restart the application workers.
If `WorkItem(code='1.2.pm')` is missing, run `python manage.py seed_work_items`
with the existing work-item specification available. No additional schema
migration is needed for the workflow fixes in this review.

Smoke-check `generate_pm_workorders --dry-run`, the PM task notification button,
one work-order completion and an existing completion edit. Rotation changes
take effect after already-issued cycles; issued history is retained.
