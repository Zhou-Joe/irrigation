# Zone editor and homepage boundary source consistency

For production zone 6-7-28 (id 5844), direct requests to both the live Gunicorn
and public HTTPS homepage APIs matched the stored DXF boundary exactly. It had
eight vertices and a clipped left corner. The manual field had eleven vertices
(including closure) and the pointed left corner the user expected. A comparison
of these actual stored coordinates matched the user's description.

The ordinary zone editor rendered `zone.boundary_points` and always saved back
to that manual field, even while `boundary_source=dxf` made the homepage use
`zone.dxf_boundary_points`. This is a real source inconsistency; the previous
homepage freshness fix did not resolve it. The database alone does not establish
whether a user imported an unintended shape or whether one version is newer.

After reviewing the comparison, the user explicitly confirmed that the left,
pointed version should be active. Production 6-7-28 was switched to `manual` by
updating only its source and update timestamp. Both geometries and the DXF source
filename were preserved exactly against a pre-change snapshot.

Release `ac1e43d9` makes the ordinary zone editor load the active geometry and
identify its source/file beside the map. The form submits the source it loaded;
saving modifies that same source and preserves the inactive geometry. Stale
forms with a different source are rejected before saving metadata or geometry.
Clearing an active DXF boundary through this form is rejected so its old manual
backup cannot silently reappear. The user can manage source selection through
the CAD import page. This release does not change the separate quick/batch drawing
workflows.

319 Django tests completed successfully with one existing CAD fixture skip.
Regressions cover active-source rendering, DXF/manual writes preserving the
other version, stale forms, invalid/empty DXF saves and homepage/editor equality.
Five focused source/revision tests also passed on the production Python runtime.

The production release used a fast-forward merge, Django checks and service
restart. No schema migration or static asset change was needed. Read-only
post-release verification confirmed the editor renders the pointed version and
both the local and public homepage APIs return exactly the same geometry with
`private, no-store`. Both saved geometries still match the backup. Recovery files
are under `deployment_backups/zone-editor-source-20261106/` on the office server.
