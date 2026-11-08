# Admin views, batch locations and component updates

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

Final validation and production checkpoint details will be recorded after rollout. No schema migration or account bootstrap is required by this follow-up. Existing production users, locations, memberships, boundaries and work orders must be preserved.
