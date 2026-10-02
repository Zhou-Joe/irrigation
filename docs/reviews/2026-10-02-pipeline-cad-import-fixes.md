# Pipeline CAD import — initial fixes

Implemented the correctness fixes and preserved-source/calibration foundation from the [approved review](2026-10-02-pipeline-cad-import-review.md). This document records the initial release. The [subsequent guided-import release](2026-10-02-pipeline-import-ux.md) supersedes the positioning UI and eligibility rules below: new positioning requires three noncollinear controls and an independent check point, and unverified default/legacy transforms are no longer importable.

## Behavior delivered

- Preview includes all extracted layers, block linework, valve candidates, and full labels. Extraction counts and per-entity unsupported/degenerate reasons are visible. TEXT placement, open-curve endpoints, OCS conversion, and MINSERT expansion are corrected.
- A signed, user-bound, 15-minute preview pins the file hash and calibration snapshot. Import rejects missing, tampered, expired, cross-user, or mismatched-file previews. Selected mappings and the displayed translation are recorded on the batch.
- New imports retain original CAD geometry, source handles/insertion paths, attributes, full plain-text notes, and calibration snapshots. Pipeline vertices and valves retain source coordinates and their last derived map coordinates.
- New calibration selections are scoped to the drawing hash. Saving and importing require a finite, nondegenerate fit and RMS validation at or below the configured threshold, default **5 m**. Similarity is the default UI choice. Legacy global calibration remains a fallback until a drawing is calibrated/reset.
- Reset preserves calibration history and batch snapshots. The UI applies calibration only to a selected import batch. Reprojection uses original coordinates; unchanged controls/method leave geometry unchanged. Manual map adjustments are carried forward. A vertex-count conflict aborts the entire operation before coordinate writes. Changed operations write a backup first; backup failure aborts without coordinate writes.
- Included block instances that cannot attach within 1.5 m are retained with their source identity and reason. The import result provides clickable locations. The dashboard has independent **CAD reference**, **CAD notes**, and **pending devices** layers. CAD reference and notes default off; pending devices default on. Attached valve details include retained attribute notes.
- The import page sets its CSRF cookie, including an authenticated visit without a pre-existing cookie.

## Verified sample

`Test dxf.dxf`, default calibration, default pipe/block selections, both original text layers, and empty operational zone associations:

| Measurement | Result |
|---|---:|
| Extracted/previewed paths | 1,982 |
| Of these, block line geometries | 1,031 |
| Full plain-text labels | 405 (334 top-level + 71 within blocks) |
| Block candidates | 515 |
| Selected block instances | 509 |
| Pipeline paths created | 542 |
| Attached valves | 410 |
| Pending devices retained | 99 |
| Valves named from nearby labels | 305 |
| Unsupported/degenerate diagnostics, including virtual block entities | 143 |

Pipeline row counts differ from source entity counts because connected entities are merged into paths. Unselected geometry remains available as CAD reference without becoming operational pipeline rows. Twenty inserts' parsed attribute dictionaries are retained with the drawing; attached assets also retain their attributes and attribute notes.

The previously reported local calibration 66 is now rejected with **246.10 m** validation RMS against the 5 m threshold. It was checked read-only; no existing calibration was edited. The default calibration is an initial alignment only: this work does not establish survey accuracy for satellite imagery or underground assets.

## Validation

- **48 DXF tests passed** in a disposable SQLite database and isolated memory caches: original mathematics/sample tests plus geometry completeness, preview/commit consistency, calibration scope/history, manual corrections, nonlinear source reprojection, idempotence, backup failure, and rollback regressions.
- Upgraded an isolated schema from **0128 to 0129** with legacy fixtures. Verified both import-time and effective calibration snapshots were preserved and no calibration history was deleted.
- Django reports no model/migration drift. JavaScript syntax and Git whitespace checks pass.
- Browser checks used a disposable local app: uploaded/analyzed/imported the sample successfully; toggled final-map reference and note layers; verified retained pending devices. No browser console errors were observed. A synthetic zone supplied the dashboard viewport and did not participate in import matching.

Run the DXF suites with the project's Python environment and an isolated test database/cache configuration:

```sh
python internal_server/manage.py test core.tests_dxf core.tests_dxf_integrity
```

## Upgrade and existing imports

Migration **0129_dxf_source_and_calibration_state** must be applied before running this code. Back up the deployment database, run `python internal_server/manage.py migrate`, and serve the updated static files using the normal deployment procedure. The existing workspace database was not migrated or altered during this implementation.

The migration freezes historical batch transforms; it cannot recover CAD coordinates that the previous importer never stored. Existing batches created under similarity can use its analytical inverse once to recover source coordinates. Existing nonlinear batches without source coordinates require the original drawing to be re-imported for repositioning. Existing deleted calibration history cannot be reconstructed; verify provenance before moving affected legacy batches.

For the reported drawing, reset the inaccurate current drawing calibration, analyze again, choose well-distributed matching points with the default similarity method, review error, and import. To reposition an existing batch with retained source coordinates, choose that batch, save its calibration, and apply it. A scale change above 15% or rotation change above 10° still requires explicit review.

## Remaining phases

Persisted independent check points and the guided alignment flow are delivered in the subsequent release. Explicit units/CRS conversion remains planned. Two-point fits cannot establish independent accuracy and are now ineligible for new positioning.

Reusable attribute mapping presets, CSV joins, editable unmatched-device attachment, annotation associations, viewport loading for much larger drawings, batch rollback/revision diffs, and interior-junction topology remain planned. The import preview now has opt-in, zoom-gated notes. Original uploaded DXF bytes are not archived; normalized supported geometry, file hash, metadata, and diagnostics are stored per batch. Detailed CAD styling and unsupported objects such as hatches are not reproduced.
