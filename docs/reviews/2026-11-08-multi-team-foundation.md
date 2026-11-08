# Multi-team foundation — local pilot increment

Branch: `codex/multi-team-foundation`. The user approved starting the expansion
and testing on a local server; this increment has not been deployed to production.

Implemented an opt-in `operations` Django app with businesses, teams, active
memberships and scoped roles; account/membership checks run on the server.
Managers can manage ordinary members only in their team; platform superusers
can grant manager memberships and create accounts without assigning global
staff or legacy manager profiles. Switching context and changes to sharing,
memberships and locations are audited.

The neutral place model has UUID identities, optional per-team codes, place
types, optional parents and optional map points. An irrigation zone can be
explicitly referenced and shared with selected teams; geometry is resolved live
from the existing active manual/DXF source. No source geometry is duplicated or
changed. Recipients cannot edit/regrant the source, and the map payload exposes
only permitted place metadata and geometry, not irrigation notes/work histories.

The supplied reference document imports idempotently by content version into
215 entries: 208 ordinary nodes and seven attached steps. Original parent-child
paths, ordering, repeated labels and source lines are retained. It is read-only
reference material, not published executable procedure logic.

New-team users are denied legacy irrigation data, pages, exports, AI and media,
including token access. Legacy access in the opt-in mode requires a membership
in the explicitly designated compatibility team and a matching legacy role;
new manager/viewer memberships cannot elevate an old global profile. The old
irrigation application remains a single compatibility scope; its internal
endpoints have not all been converted to arbitrary sub-team row scoping.

Default `MULTI_TEAM_ENABLED=False` preserves current production behavior. An
explicit bootstrap command creates the two businesses and can map existing
accounts to irrigation memberships without reactivating retired memberships
or adding existing new-team users to irrigation. The new pilot login/PWA entry
is neutral; public shell assets remain accessible to pest-only accounts.

Validation included the 344-test core/foundation suite (one existing skip),
follow-up tests for the final account/PWA/link-collision paths, and all 80 Node
tests. Migration state checks report no drift. Browser checks verified desktop
and 390px layout, live map rendering, nested catalogue steps and a dual-role
switch from pest manager to irrigation field worker with manager controls
removed. Screenshots are in `docs/reviews/assets/2026-11-08-*`.

The local runner uses `.tmp-pm-review/multi-team-preview/db.sqlite3`, isolated
media/AI directories, loopback binding and an in-memory email backend. It leaves
real databases and production services untouched. Test instructions and demo
accounts are in `docs/plans/2026-11-08-multi-team-foundation-testing.md`.

Next: pest case/visit records, owned work-record services, approved executable
forms and general plan targets with business-scoped rotation pools. Do not put
pest plans into the legacy frequency-only rotation groups before that work.
