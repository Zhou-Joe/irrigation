# Current boundary source on zone details

Release `4fe96a27` adds the effective boundary source below the zone detail
header badges. It shows manual drawing, DXF import with its escaped source
filename, or no boundary. The conditions follow `active_boundary_points`,
including fallback to manual geometry when the selected DXF field is empty.
Long filenames wrap on narrow screens.

Local template rendering verified manual, DXF, empty and DXF fallback cases,
including filename escaping. Production rendering verified zones 6-7-28
(manual) and 2-3-7 (DXF). Django checks passed and the restarted service is active.
All zones' stored boundary sources, geometries and DXF filenames match the
pre-release fingerprint. No migration or static collection was necessary.
The prior template and verification results are retained under
`deployment_backups/zone-detail-source-20261107/` on the office server.
