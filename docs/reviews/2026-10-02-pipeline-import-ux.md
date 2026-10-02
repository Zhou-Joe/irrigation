# Guided pipeline import and verified positioning

Implements the user's follow-up to the [CAD import review](2026-10-02-pipeline-cad-import-review.md): improve the import experience and remove positioning choices that could silently distort or misplace a drawing. Builds on the [source-integrity fixes](2026-10-02-pipeline-cad-import-fixes.md).

## Delivered workflow

1. **Upload:** choose or drop a DXF file. Parse the complete supported drawing in its original coordinates and immediately overlay it on the satellite map, explicitly labelled as preliminary and unverified. Changing files clears points, coordinate inputs, preview authorization, selections, and review confirmation.
2. **Choose:** searchable tabs for pipeline layers, devices, and notes; visible source-entity counts; explicit diameter units and device types; click a layer name to locate it. Block symbol linework stays reference-only and cannot be imported as pipeline rows, including through the API. All supported original geometry and full notes remain retained, including unselected content.
3. **Align:** use **one satellite map with CAD overlaid**. First move, rotate or uniformly scale the preliminary overlay to identify matching features. Click an overlaid CAD vertex/device; temporarily hide CAD to click its counterpart in the satellite image, then automatically restore the overlay. A retry button cancels the pending point and restores CAD. Each completed control pair updates the overlay, so the user can find the next feature. Coarse adjustments lock once pairs exist. Measured CAD/WGS84 coordinates remain available. Require at least three distinct, noncollinear controls and a different, independent check point. Display per-point residuals, fit RMS, metres per CAD unit, and check-point errors, with source/target markers and residual connectors on the same map. Independent points never participate in fitting. Save rechecks the criteria on the server and refreshes the signed preview. The native CAD view is an optional auxiliary dialog, rather than a second main map.
4. **Review/import:** show the selected content and alignment checks, require review confirmation, and disable repeat submission after success. Immediately display created pipelines, attached devices, retained pending devices, and full-note counts, with links to the map and locations of pending devices.

The workspace has separate switches for CAD visibility, original reference linework, devices, notes, and existing operational pipelines, plus adjustable overlay opacity. Existing pipelines are optional grey dashed lines, initially hidden. Notes are initially hidden, appear after zooming, and use short on-map text with full text in popups. The sidebar scrolls independently on desktop; narrow screens show one full-width map above the guided controls. Busy operations lock drawing and mapping changes.

## Positioning changes

New import and batch-repositioning endpoints accept only **uniform similarity alignment**: translation, rotation, and one scale, with longitude normalized for latitude. The interface no longer offers automatic TPS/MLS selection, nonlinear deformation, an accepted exact two-point mode, inverse-based CAD point picking, or persistent unverified whole-drawing offsets. Preview-only coarse adjustments do not change source coordinates or authorize import.

Initial visual placement uses a usable historical similarity hint near the current project view. If it cannot place the drawing in that view, it uniformly fits the raw extent around the map centre. This deliberately makes the drawing visible without claiming to infer its CRS, units, or surveyed location. One control translates the preview; two controls provide a visual similarity fit; three suitable controls provide the full draft fit. These intermediate previews never bypass the independent-check gate. CAD picking searches forward-projected original vertices, including visible reference linework and devices, rather than inverse-projecting an approximate map click.

Control RMS, every control residual, and every independent check-point error must be at or below `DXF_CALIBRATION_MAX_RMS_M`, currently **5 m**. Duplicate/reused points, collinear controls, nonfinite coordinates, invalid map coordinates, missing checks, old methods, and nonzero drag offsets are rejected. The browser may display provisional forward-projected positions before validation; the API still withholds accepted geographic preview coordinates and import eligibility until positioning passes.

Historical transforms remain available internally to reproduce existing batch geometry and preserve provenance. Migration does not rewrite or delete them. Legacy/default records without independent checks cannot authorize a new import or repositioning. This is a workflow eligibility rule, not a claim that nonlinear mathematics is universally invalid.

Repositioning loads the chosen batch's retained source drawing and original mapping choices. Its controls are scoped to that drawing hash, and applying them moves only the chosen batch. An in-page confirmation identifies the selected batch and explains the backup and preservation of individual edits; large scale/rotation changes require a second explicit confirmation. It removes a recorded legacy whole-drawing offset, preserves individual map edits relative to the last derived baseline, and writes a backup containing prior geometry, calibration snapshots, and import options before changing coordinates. Changed vertex counts and backup failures abort the operation. Identical transforms without a legacy offset leave geometry unchanged.

## Verification

- **62 Django CAD tests pass** in isolated SQLite/memory caches: geometry completeness, preview/commit consistency, source preservation, historical reprojection, backup/rollback, and the new public alignment policy. Regressions cover missing/incorrect/reused check points, collinear/duplicate controls, retired methods, drag-offset rejection/removal, preserved individual edits, batch source/mapping retrieval, large-change confirmation without premature coordinate writes, and the single main map with an auxiliary raw-view dialog.
- **6 JavaScript regressions pass** using Node's built-in test runner: shape/source preservation under coarse adjustments, visible viewport fitting of unknown source coordinates, incremental one/two-point preview without eligibility, independent-check rejection without changing the fit, dirty drawings no longer using stale accepted coordinates, and invalid preview coordinate suppression.
- Browser QA used a disposable local database and the repository's `Test dxf.dxf`. The raw preview contained **1,982 paths, 515 block instances, and 405 full notes**. The selected sample import produced **542 pipe paths, 410 attached devices, and 99 retained pending devices**. Source counts differ from pipe row counts because connected source entities are merged.
- A synthetic check point displaced by 11.13 m visibly disabled saving and progression while fit RMS stayed 0.00 m. Correcting the check enabled server validation, review, and import. The revised browser flow also exercised initial same-map overlay, coarse drag/rotation/uniform scale, forward CAD picking in the overlay, automatic hide/restore, retry, and the auxiliary native-view dialog.
- Loaded an existing batch, saved its independently checked alignment, exercised cancellation, then confirmed repositioning of its 542 pipes and 410 devices. Drawing reset and batch loading clear stale coordinate inputs and start with the control-point role.
- Checked desktop and **390 × 844** mobile layouts; mobile document width was exactly 390 px, with no horizontal overflow. No browser console errors observed in the successful workflow.
- JavaScript syntax, Django model/migration consistency, and Git whitespace checks pass.

Browser control/check coordinates were synthetic fixtures generated from a known transform to test workflow consistency. They do **not** establish that the drawing matches real surveyed assets or that the satellite imagery has survey accuracy. Users must select actual identifiable counterparts or measured coordinates; distribute controls and checks across the drawing. The minimum 3+1 gate does not prove accuracy everywhere between points.

Test command, using the project's environment and isolated database/cache settings:

```sh
python internal_server/manage.py test core.tests_dxf core.tests_dxf_integrity core.tests_dxf_alignment
node --test internal_server/static/js/dxf-import/tests/placement.test.cjs
```

## Upgrade

Apply migrations **0129_dxf_source_and_calibration_state** and **0130_dxf_independent_check_points**, then serve the updated static files, including `dxf-placement.js`, using the deployment's normal process. Migration 0130 adds an empty independent-check list to existing calibration rows; it deliberately does not invent validation points. The single-map correction adds no schema changes. This round of tests and browser QA used disposable databases.

Old batches with no retained raw drawing must upload the original DXF again for this guided workflow. Historical deleted controls and CAD information the old importer never stored cannot be reconstructed automatically.

## Further enhancements

The original review's next priorities remain: explicit unit/CRS selection and conversion; reusable block-attribute mappings and CSV joins; editable pending-device attachment; associations between notes and pipeline/assets; batch revision comparison and rollback; larger-drawing viewport loading; and interior-junction topology. This release preserves the metadata needed for those features but does not implement them or archive original DXF bytes.
