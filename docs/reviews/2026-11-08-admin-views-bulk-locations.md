# Admin views, batch locations and component updates

The role-preview selector and import-first map creation described here are superseded by `2026-11-08-map-business-interactions.md`; this file retains the initial rollout record.

This follow-up keeps the irrigation interface and the map as the primary page. Pest control uses the same map action layout, form shell, common fields and work-category chips. Location selection uses a searchable, paginated list with type filtering and map selection rather than a chip for every location.

## Account correction

The production admin already has real superuser/staff permissions. Its Worker row exists for historical attribution and must remain. Profile and account-list labels now resolve the effective account role instead of treating every Worker association as a field account.

A real platform superuser can choose irrigation manager/field or pest manager/field views on the map, then return to the full platform view. The selection lives in the session; no membership or real permission is rewritten. Field previews use personal/crew PM data and personal pest records. Normal users cannot forge an admin preview, and inactive teams are rejected. Platform administration remains accessible.

## Batch operations

Managers can paste names or tab-separated Excel rows, or upload UTF-8/GB18030 CSV, preview up to 500 locations and create them atomically. Optional fields cover arbitrary codes, types, parents, coordinates and descriptions. Validation rejects duplicate codes, invalid coordinates, parent cycles and unavailable parents before writes. Submission receipts protect against duplicate retries and verify the current team before replay.

Owned locations can be shared or revoked in batches, by selected rows or all matching results (maximum 1,000). Irrigation zones can be referenced and shared in one operation without copying geometry. Receiving teams have read-only access and cannot regrant. Real platform admins can select irrigation sources while staying in the pest view. Normal pest managers cannot expose private irrigation zones.

## Interaction rule

State-changing actions update elements instead of reloading the page. Searches and pagination replace only results; saves and sharing update status/list elements; successful map submissions refresh only overlays. Same-business role changes retain the map instance. Business changes replace only the dashboard component, preserving map center/zoom and cleaning old timers, listeners and overlays. PWA navigation identity and notification data refresh with the selected view. Requests from disposed components cannot repaint the current map. No new whole-document reload is used.

Existing service-worker update/offline recovery controls and deliberate page links retain their established behavior. UI acceptance is left to the user as requested.

## Validation and deployment

Local validation: Django 382 cases (381 passed, one existing skip), Node 93 cases passed, JavaScript syntax checks and migration drift check passed. The additional request-lifecycle cases verify stale metadata rejection, cancellation on disposal, and submission guards through response parsing. No schema migration or account bootstrap is required by this follow-up. Existing production users, locations, memberships, boundaries and work orders were preserved.


Production is running application commit `4f8a262c125cbb71330474a383048908d49d0a1f` on `codex/multi-team-foundation`. The private fresh checkpoint is `/home/noname/irrigation/deployment_backups/admin-role-bulk-20261108-221510/`: previous tracked-source archive, environment and service/cron configuration, plus online and fresh stopped-service backups of the primary database and both AI checkpoint databases. Every backup passed SQLite integrity checks. The previous complete media backup remains in the original multi-team checkpoint; this update changes no media schema.

The candidate was rehearsed against a restored current production database. Real admin profile labels, all four role views, existing pest accounts and hierarchy endpoints passed. Batch preview, creation, retry and sharing were exercised only in the database copy, with test writes rolled back. Candidate static files were collected before cutover.

The first cutover passed application and exact data-preservation checks, then stopped on the system crontab tool truncating a long restore-file path. The previous code/static version was recovered without restoring or discarding business data. The helper was changed to restore cron content through standard input; the original schedule was restored, first-attempt snapshots retained under `attempt1`, and fresh cutover backups taken for the successful retry.

Final production checks passed for admin labels, role switching, map/hierarchy/work records and both existing pest accounts. Temporary verification session and audit writes were rolled back. All original table contents matched the fresh pre-cutover row hashes exactly. `horticulture` is active/running with `ExecMainStatus=0`, and all six original application cron entries are restored.

Public HTTPS login, manifest and updated JavaScript returned HTTP 200 from the tunnel endpoint. SHA-256 hashes for workspace, shared map controls, batch UI, location picker and irrigation modal scripts match the tested application commit. Local isolated preview at port 8786 was restarted. No browser visual or interaction acceptance was performed, as requested.
