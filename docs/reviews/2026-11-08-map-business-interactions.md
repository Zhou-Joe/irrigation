# Business selection and direct map placement

This follow-up replaces simulated manager/field views with a business selector containing only 灌溉 and 植保. Available businesses come from actual account access; modules, record scope and management actions use real account/team permissions. A platform admin retains admin rights in both businesses. Old preview sessions retain the business but no longer impersonate their selected role. Memberships, account flags and attribution rows remain unchanged.

The unsubmitted-work-order close confirmation and the business-switch confirmation are removed. Switching stays within page components and retains map center/zoom. A submission/save already in progress blocks switching with a nonmodal status message. Existing business duplicate-submission confirmations remain part of their original workflows.

Pest location creation is now direct map placement. A manager chooses 新增地点, taps a position, enters a name and chooses 保存并继续, then places the next location. Type defaults to building; code is optional. Coordinates come from the map and are never required as user input. A compact card leaves the map interactive; no page redirect or reload is used. Successful creation refreshes only pins/list data and keeps the map viewport; failed/retried requests retain draft data and submission receipt protection. File import remains an optional tool on the existing management page.

The irrigation layer menu includes 共享地点, enabled by default. It renders only other teams' locations explicitly granted to the current irrigation team, with the same typed pins or shared boundaries. Owned irrigation zones are not duplicated. Updates respect revocation, use private/no-store responses and never move the map. The layer can be hidden independently, retried in place and refreshed on returning to the map or periodically while visible. Shared locations remain read-only.

Manager modules in the pest PWA launcher follow actual membership permissions. The AI launcher follows real staff/superuser eligibility in either business; its endpoints retain their existing server authorization. Revoked selected business access cannot silently fall back into another business.

Validation: full Django regression 384 cases (383 passed, one existing skip), followed by 13 focused account/business/map-placement/shared-layer checks, all passed. Node 96 cases passed, including coordinate validation, consecutive placement, receipt reuse after a failed request and an in-flight duplicate guard. UI acceptance is left to the user; no browser visual checks were performed. This update requires no schema migration.

Production rollout details will be appended after verification.
