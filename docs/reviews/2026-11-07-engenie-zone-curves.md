# EnGenie and curved CAD zone boundaries

Zone DXF parsing previously read only polyline XY vertices, dropping the bulge
values that encode circular arcs. Both closed LWPOLYLINE and 2D POLYLINE now
sample the true arcs, including the closing segment and clockwise/major arcs.
Original straight vertices and their precision are retained. Sampling uses at
most 5 degrees per chord and 0.05 drawing units of sagitta, with a safety cap of
4096 segments per arc. OCS conversion covers the sampled geometry as well as
the original vertices. Two-vertex circles are accepted after expansion; polygon
meshes are excluded.

Existing stored boundaries cannot recover discarded arc data: upload the source
DXF again and assign its shapes to update those boundaries. This release does
not rewrite existing zone geometry or require a migration.

The irrigation assistant now uses EnGenie throughout its launcher, header,
welcome, response avatars, composer and accessible labels. The original arrival
script, stylesheet, six artwork assets and four animation regressions are copied
from the sibling RAG project. Opening the welcome view replays the 2.56 second
arrival; reduced-motion preferences and failed downloads use the still pose.
The interruptible panel open/close behavior is adapted from the RAG widget.
The irrigation conversation APIs, retention policy, tools and data remain in use.
Dashboard asset versions are refreshed for production caches.

Validation: 66 targeted Django regressions passed (one existing sample-file test
skipped), including new geometric direction, radius, area, chord-error, OCS and
preview-to-assignment-to-homepage checks. All 13 chat-core/arrival JavaScript
tests passed. The actual local dashboard rendered the EnGenie launcher and
welcome with no browser warning/error logs.

Production: deployed `a83942bb` directly through the existing office SSH tunnel
using a Git bundle. The production checkout fast-forwarded from `4fe96a27`;
Django checks passed, 10 static files were collected, and `horticulture`
restarted at 2026-11-07 15:53:56 Asia/Shanghai with active/running status and
ExecMainStatus=0. Collected chat JavaScript and arrival GIF hashes match their
source files. The prior revision, source archive and release bundle are retained
under `deployment_backups/engenie-zone-curves-20261107/` on the office server.
No migrations or stored zone-boundary updates were performed. The user will
inspect the deployed visual behavior.
