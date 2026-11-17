# Multi-team production pilot — 2026-11-08

Deployed application revision: `06ad6e7f567f649213c3d08e8b2cd0b209b465a8`, branch `codex/multi-team-foundation`. Production previously ran `a83942bbbec742f9e0622a7f21a99846c7ca03ec` on `main`. The feature is enabled through the existing private `.env.production` (`MULTI_TEAM_ENABLED=True`). GitHub `main` was not changed.

## Checkpoint and backups

Private production backup directory:

`/home/noname/irrigation/deployment_backups/multi-team-20261108-202004/`

The initial checkpoint contains a verified Git bundle, full tracked-source archive, production environment file, service unit, collected static files, media/private attachment archive, and SQLite online backups of:

- `internal_server/db.sqlite3`
- `internal_server/media/ai_checkpoints.sqlite3`
- `internal_server/private_ai/checkpoints.sqlite3`

Every database backup passed `PRAGMA integrity_check`. File sizes and SHA-256 hashes are recorded in `checkpoint.json`; initial backup size is 6,204,417,805 bytes. The prior Git revision is also tagged `checkpoint/pre-multi-team-20261108-202004` on the server. Credentials, production databases, environment values and media have not been added to GitHub.

Fresh database snapshots and an environment copy were taken with the application stopped immediately before cutover. `cutover.json` records the original table columns, row counts and row-content hashes. The prior live static directory is retained as `static-live-before`.

## Rehearsal and release

Before changing the live checkout, the release was extracted into `candidate`, migrations and bootstrap were run against a restored database copy, and static files were collected separately. All original business-table contents remained identical. Representative existing roles opened the original irrigation map. Pest manager/field permission checks, native building pins and a real work-order submission passed in the copy; no rehearsal locations or work orders were copied into production.

The first cutover stopped on a missing remote-tracking branch before applying code or migrations. The original service and cron entries were restored. Explicit branch tracking was configured and verified before the retry; first-attempt snapshots remain under `cutover-attempt1`.

During the successful cutover, six application cron entries were paused and existing management jobs were allowed to finish. The service was stopped, current databases were backed up again, then code, static files, schema and account mapping were updated. The service and all original cron entries were restored afterward.

Applied schema changes: `operations.0001_initial`, `core.0138_workreport_business_team`, `operations.0002_pestworkdata`, `operations.0003_location_map_display`.

## Data and accounts

- All original business rows were verified against the fresh pre-cutover snapshot using the original columns. The irrigation work-order count remained 1,859.
- Twenty-two existing effective irrigation accounts received matching team memberships. Their legacy roles and global permissions were retained.
- Existing irrigation is the default for accounts that later gain additional team memberships. Department login redirects and legacy staff admin access remain compatible. Newly approved legacy registrations also receive their irrigation membership.
- The supplied pest hierarchy was imported with 215 entries; this creates no PM schedules or dispatches.
- Two newly authorized test accounts were created: `pest-test-manager` and `pest-test-field`. They have only their pest-team roles, with neither staff nor superuser privileges. Their distinct random passwords are stored privately in the backup directory and delivered to the user separately.
- Existing irrigation zones were not automatically granted to the new team. Managers can create building pins; irrigation owners can explicitly share selected existing zones through `/ops/locations/link-irrigation/` and the location-sharing controls.

## Validation

Local regression: Django 364 cases, 363 passed and one existing fixture case skipped; Node 87 cases passed. Migration drift check passed. Production rehearsal additionally checked existing row-content hashes and role compatibility against real data.

Live checks passed for both new roles at the map, map-data, hierarchy form and work-record URLs, while access to irrigation-only data remained denied. No fake production work order was submitted. Live Django checks and SQLite integrity checks passed. `horticulture` is `active/running`, `ExecMainStatus=0`; login, manifest and new static resources returned HTTP 200 through the local production listener with the production host header.

Public HTTPS was checked from the Aliyun tunnel endpoint: login, manifest, map-marker JavaScript and stylesheet returned HTTP 200 through `https://irrigation.zctestbench.asia`. Both static-file SHA-256 hashes match the tested Git objects. Direct TLS checks from the development computer were reset; the public endpoint check succeeded from the tunnel host.

UI and interaction acceptance remain with the user, as requested.

## Rollback reference

Quiesce the application and application cron entries before restoring. Return to the recorded prior Git revision; restore the latest pre-cutover primary database, environment and `static-live-before`; restart the service and reinstate the captured cron configuration. Preserve any subsequent live writes before rolling back. The saved source/bundle, database snapshots and media archive provide the wider recovery checkpoint.
