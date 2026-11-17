# DXF valve shapes and internal symbol text

DXF import now proposes independent polyline valve symbols as devices. Previously,
only INSERT blocks could create `PipeValve` records; an exploded valve could be
included in pipe geometry instead. Short internal block text such as `WD` also
disappeared when ordinary annotations were hidden.

## Import and review

- The device tab lists common bowtie silhouettes and symbols identified by
  internal codes, alongside existing block candidates. Users review the device
  type before importing. Bulk type selection and candidate zoom are supported.
- Users can box a complete example containing up to 20 source entities, name its
  type, and save it for other drawings. Geometry comparison removes translation,
  rotation, reflection and axis scale; it tolerates different vertex sampling.
  Ordinary straight pipes and simple elbows are rejected as teaching samples.
- Shape similarity does not establish equipment semantics. Untyped common shapes,
  unlabeled round templates and examples missing their expected text remain
  unchecked. A candidate can be omitted without changing the previous pipe import.
- Reviewed symbol geometry is excluded from pipe creation. Clear opposing pipe
  endpoints receive a center bridge; uncertain connections retain the existing
  nearest-pipe attachment rule and unmatched-device review.
- Full original geometry remains in the import batch, including device outlines,
  labels, source entity references, template identity and recognition score.
- Internal `WD` text stays with the CAD symbol layer when ordinary annotations
  and reference lines are hidden. Block names without useful semantics can use
  their own internal code. Device-only drawings retain unmatched devices without
  creating artificial pipes.

## Persistence and access

Migration `core.0145_dxf_valve_shape_templates` adds one table and one conditional
unique constraint. It does not modify existing pipe, valve or work-order rows.
Templates share the irrigation DXF manager gate. Creation requires CSRF and source
entity references resolved on the server; only the creator or an administrator can
soft-delete a template. Deleting an example does not delete imported devices.
The parser cache version advances to v4.

## Validation

- 98 Django DXF/feedback regressions pass (one pre-existing skip); 141 operations
  regressions pass. JavaScript suites pass 131 tests, including map initialization,
  symbol-layer visibility, escaping, review selections and cross-drawing state.
- Retained production drawing `Mainline- 05 sting.dxf`: 303 original paths,
  61 matching bowtie candidates. In an isolated browser import, reviewing all 61
  creates 139 pipe segments and 61 attached devices; 36 clear symbol gaps receive
  bridges. The original 303 paths are retained. Omitting symbols retains the
  previous 236-pipe result for that drawing and its original pipe type.
- A custom concave example is taught through the two-corner selection UI and
  matches three rotated, mirrored and differently sized instances in a second
  drawing. The first custom drawing imports three pipes and three valves.
- The three `WD` examples from the reported live parse are exercised as opaque
  blocks and as independent polylines. Blocks without pipes retain three unmatched
  devices; polylines on a pipe create one pipe and three attached valves. WD text
  stays visible with ordinary notes off and follows the device visibility toggle.
- Desktop and 390px mobile review controls are visually inspected; mobile type
  selectors retain 44px touch height and no horizontal page overflow.

Existing imported batches are not automatically reclassified. They retain their
existing records until an explicitly reviewed import is performed.
