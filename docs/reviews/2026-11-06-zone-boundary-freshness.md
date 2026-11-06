# Homepage freshness after DXF boundary changes

Production zone 6-7-28 (id 5844) already had `boundary_source=dxf`, a populated
DXF boundary from `Zone -6.dxf`, and a different preserved manual boundary. The
homepage server payload exactly matched the DXF geometry. The stale display path
was the retained homepage: it refreshed only on a BFCache return after 60 seconds,
and did not check for edits while remaining open or regaining focus. Browser JSON
caching also allowed a previous payload to be reused.

Release `e711c253` uses an authenticated, no-store lightweight Zone revision
endpoint. Returning to a retained homepage, regaining focus and becoming visible
check for changes; a visible homepage also checks every 30 seconds. A changed
revision reloads zone geometry without reinitializing the map or imagery. The
payload and its fetch bypass browser caches; its revision is captured before
building the payload to avoid hiding a concurrent edit. Static script URLs were
versioned so a fresh homepage loads the fix.

310 Django tests ran successfully with one existing fixture skip; all 74 Node
tests passed. Regressions cover manual-to-DXF source changes, response revisions,
cache bypass and refresh suppression for unchanged, hidden or loading maps.
The targeted regression also passed on the production Python runtime before
release. Django checks, static collection and service restart succeeded. The
post-release homepage payload still exactly matches 6-7-28's DXF, its revision
matches the lightweight endpoint, and saved manual/DXF boundaries are unchanged
against the pre-release snapshot. Public login returns HTTP 200.

No migration or business-data write was needed. Recovery snapshots are under
`deployment_backups/zone-refresh-20261106/` on the office server. An already-open
homepage needs one reload to replace its previous JavaScript; subsequent checks
run automatically.
