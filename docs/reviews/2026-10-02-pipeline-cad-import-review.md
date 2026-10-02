# Pipeline CAD import review — 2026-10-02

This review describes the original code. The initial fixes are documented in [implementation status](2026-10-02-pipeline-cad-import-fixes.md).

Reviewed commit `3e5b9cc2`, the confirmed affected drawing `Test dxf.dxf`, the Django import/calibration endpoints, Leaflet preview and dashboard rendering, models, and existing DXF tests. Application code and the existing database were not changed. Database inspection used SQLite read-only mode; import and recalibration experiments used disposable databases and caches.

The strongest findings are incomplete CAD block display and unsafe calibration state. The current parser collects all supported, nondegenerate top-level line entities in this sample. A reduced pipeline row count alone is not evidence of missing lines: the importer merges connected entities into paths.

The local database contains 60 calibration records but no pipelines, valves, or import batches. Its latest calibration is row 66, saved on September 4. These observations establish local behavior, not the deployed application's current data or the absolute ground accuracy of its satellite imagery.

**Priority findings**

1. **[P1] A very inaccurate calibration can become active for every new import.**

   [dxf_views.py:121](/Users/chen/development/maxicom/internal_server/core/dxf_views.py:121) only checks whether fitting returns a callable before saving the calibration. [_active_calibration_points:140](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:140) then selects the newest row globally, regardless of drawing or import session. The scale/rotation confirmation in the apply endpoint does not protect preview or new imports.

   Replaying local row 66 succeeds with HTTP 200 despite **246.10 m leave-one-out RMS** and individual validation errors up to **343.57 m**. Its first two points map a roughly 28.68-unit CAD baseline to 345.02 m, yielding **12.031 m/unit**, versus **0.999 m/unit** under the default calibration. The drawing's transformed extent expands from roughly 0.4 km to several kilometres. This is strong evidence of a bad calibration for this drawing, although survey controls are needed to establish the correct alignment.

   Fix: save draft calibration separately from activation; require explicit source units/coordinate system and an independent check-point assessment; reject non-finite, degenerate, implausibly distorted results and require deliberate review for excessive error. Scope the approved calibration to the drawing/import batch. Do not assume all drawings share the same local coordinate frame.

2. **[P1] Recalibration reconstructs source coordinates with an approximate inverse and can move geometry even when controls are unchanged.**

   [calibration.py:417](/Users/chen/development/maxicom/internal_server/core/calibration.py:417) fits a reverse TPS/MLS mapping by swapping control-point directions. That mapping is not generally the mathematical inverse of the forward nonlinear transform. [dxf_views.py:331](/Users/chen/development/maxicom/internal_server/core/dxf_views.py:331) uses it to overwrite saved coordinates; [dxf-cal.js:89](/Users/chen/development/maxicom/internal_server/static/js/dxf-import/dxf-cal.js:89) also uses reverse mapping to recover CAD coordinates for new control points.

   Reproduction: create geometry under local row 66's MLS mapping, mark that mapping applied, save an identical mapping, and apply it. The request succeeds with zero reported scale/rotation change, yet two test vertices move **210.18 m and 242.30 m**. Those large values depend on the poor local calibration. A separate, mildly warped 500 m test grid also produces nonzero round-trip error: about 1.4 cm for TPS and 4.4 cm for MLS. Repetition can therefore alter geometry even with better controls.

   Fix: retain original CAD coordinates and entity identity, send original coordinates with preview vertices, and always regenerate map geometry directly from the originals. Persist manual corrections explicitly. Treat unchanged calibration as a no-op. Remove the UI advice to repeat save/apply to obtain convergence.

3. **[P1] Clearing calibration history breaks later recalibration of existing imports.**

   [dxf_views.py:148](/Users/chen/development/maxicom/internal_server/core/dxf_views.py:148) deletes all calibration rows. The apply endpoint later infers each batch's old transform from those rows and its import timestamp at [dxf_views.py:210](/Users/chen/development/maxicom/internal_server/core/dxf_views.py:210). With history gone, it silently assumes the hardcoded default transform.

   Reproduction: import with calibration A, clear calibration, save B, then apply B. Using simple translations of the default calibration, the endpoint returns success without requiring force, but the result is **111.32 m** from a direct B transform of the original coordinates.

   Fix: clearing should reset a draft/current selection while retaining historical versions. Store an immutable calibration reference and transform snapshot on each batch. Scope recalibration to selected batches; manually drawn map features also need an explicit policy because the current endpoint moves every pipeline.

4. **[P1] The committed import can use a different calibration from its preview.**

   [dxf_pipeline_utils.py:983](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:983) resolves the latest calibration again at import time. The parse token identifies cached source geometry, but does not pin calibration, units, or transformation parameters. Another tab/user saving calibration—or a save whose preview refresh fails—can invalidate what the user reviewed.

   Reproduction: analyze under A, activate B with a 0.001° latitude change, then import using the original token. The imported geometry differs from the reviewed transform by approximately **111.27 m**, with no stale-preview rejection.

   Fix: create a versioned import session that records file hash, parsed source, mappings, units, calibration version, offsets, and preview result. Commit that version atomically or reject it as stale.

5. **[P2] Expanded CAD block linework is unavailable in the preview, even when selected.**

   [dxf_pipeline_utils.py:821](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:821) removes every `块·…` layer from the preview payload. The sample contains **1,031 extracted line geometries in eight such layers**, mostly valve/fitting symbols. Selecting their checkboxes cannot display them because the browser never receives those paths. These layers are also unchecked by default, so their original symbol linework is absent from the normal final import; imported valves instead receive generic map markers.

   The additional limits of 12 non-block layers and 600 paths/layer are another silent preview completeness problem for larger drawings. They are **not triggered by this sample**, which has 11 non-block layers, none exceeding 600 paths. The browser also displays only 200 labels per text layer, hiding 107 of this drawing's 307 equipment labels.

   Fix: provide a complete, independently toggleable CAD reference overlay and a separate operational pipeline/valve overlay. Load by viewport or explicit pagination with visible coverage counts. Preserve symbol linework without converting every symbol circle into a hydraulic pipeline. The selected preview and committed feature set should agree.

6. **[P2] Standard TEXT entities can abort the entire analysis.**

   [dxf_pipeline_utils.py:514](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:514) falls back to `e.dxf.start` for TEXT, which has no such DXF attribute. A valid left-aligned TEXT with only an insertion point raises `DXFAttributeError`; the endpoint converts it to a generic parsing failure. This sample uses MTEXT, so this is an additional confirmed compatibility defect, not its reported cause.

   Fix: use ezdxf's text placement/alignment API and correct coordinate conversion. The documented TEXT anchors are `insert` and `align_point`. [ezdxf TEXT documentation](https://ezdxf.readthedocs.io/en/stable/dxfentities/text.html)

7. **[P2] Downsampling long open curves adds a false closing segment.**

   [dxf_pipeline_utils.py:387](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:387) appends the first point after downsampling, before checking whether the path is closed. A half-ellipse that flattens to 535 vertices becomes an open path whose last vertex incorrectly returns to its first, adding a 20,000-unit cross-drawing segment. Other downsampling intervals can also lose the original final point. No top-level spline/ellipse in this sample triggers this branch.

   Fix: preserve both original endpoints for open curves; close only genuinely closed paths. Use an error tolerance expressed in physical units and verify it after simplification.

**Measured sample behavior**

The drawing is DXF R2000 (`AC1015`), with `$INSUNITS=0` (unspecified). Modelspace contains 847 LWPOLYLINE, 102 LINE, four CIRCLE, four HATCH, 334 MTEXT, and 515 INSERT entities. No MINSERT arrays, external references, or nondefault extrusion vectors were found in modelspace.

| Measurement | Default calibration | Latest local MLS calibration |
|---|---:|---:|
| Preview non-block paths | 951 | 951 |
| Default-selected source pipe entities | 841 | 841 |
| Created pipeline paths | 542 | 559 |
| Selected valve/block instances | 509 | 509 |
| Created valves | 410 | 364 |
| Selected instances discarded by distance rule | 99 | 145 |
| Valves named from nearby labels | 305 | 2 |

These disposable imports used the default layer/block selections, both label layers, and empty zone associations to isolate CAD geometry/label behavior. Production zone and station assignments were not validated.

Valve drops occur at [dxf_pipeline_utils.py:925](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:925): an included block without a pipe within 1.5 m is discarded. The result reports an aggregate skipped count, but does not preserve those assets for review or identify them on the map. Calibration also changes the inferred drawing scale at [dxf_pipeline_utils.py:257](/Users/chen/development/maxicom/internal_server/core/dxf_pipeline_utils.py:257), so a bad first control pair changes the pipe-join, valve-match, and label-search tolerances. This explains why an alignment problem can also reduce valve and label completeness.

Notes are currently only candidates for valve naming. The importer does not persist a general annotation layer. It also omits text inside blocks: this sample has 69 `WD` labels and two `103B` labels there. Twenty block instances have parsed attributes that are not consumed when creating valves. Top-level text is truncated to 60 characters, and matched valve names to 50. The final map cannot reproduce full CAD notes from these records.

Further confirmed compatibility gaps: MINSERT arrays return only their first instance, and LWPOLYLINE coordinates with a negative extrusion vector are mirrored because their OCS coordinates are read as WCS. Synthetic probes reproduced both; neither occurs in this sample. Use `multi_insert()` and a WCS-normalized parsing path, with explicit unsupported-entity reporting. [ezdxf INSERT documentation](https://ezdxf.readthedocs.io/en/stable/blocks/insert.html), [ezdxf polyline coordinate documentation](https://ezdxf.readthedocs.io/en/stable/tutorials/lwpolyline.html)

**Recommended enhancement approach**

There are three reasonable scopes. A repair-only release can correct the confirmed defects quickly but leaves notes and source traceability limited. A phased import wizard with preserved source geometry addresses the reported problems and future drawing updates; this is the recommended direction. A larger GIS/network-management rebuild can follow if connectivity analysis and substantially larger datasets become requirements.

| Phase | User-facing outcome | Implementation and acceptance criteria |
|---|---|---|
| 1 — Correctness | The user can account for everything visible in CAD and trust the reviewed position. | Fix preview exclusions, TEXT and curve defects; pin calibration to preview/commit; retain calibration history; preserve original coordinates; show accepted/excluded/unsupported/unmatched counts and clickable reasons. Every source entity must have an explicit disposition. |
| 2 — Guided alignment | Upload → inspect CAD → align → validate. | Ask for drawing units and coordinate system, showing that this sample's units are unspecified. For known georeferenced CAD, use its declared CRS conversion; for local CAD, fit well-distributed control points and retain independent checkpoints. Prefer similarity by default, with affine/nonlinear modes chosen for demonstrated distortion. Display residual vectors, check-point errors, coverage, and extrapolation warnings. Require the agreed accuracy tolerance before activation. |
| 3 — Valves and notes | Map CAD layers/blocks/attributes to pipelines, valves, and annotations, then resolve uncertain matches. | Provide reusable mapping presets. Map attribute tags to asset ID, type, diameter, station/zone, and notes. Preserve full TEXT/MTEXT/ATTRIB content and placement. Keep unmatched assets in a review queue with candidate pipe links and distances; allow standalone assets where appropriate. Support a CSV asset register joined by stable identifiers. |
| 4 — Display and updates | Operators can search and inspect imported assets, compare revisions, and understand map symbols. | Separate pipelines, valve symbols, notes, CAD reference, and import-quality layers; distinguish valve type by shape and operating state by colour; add zoom-aware labels with explicit visibility controls. Asset details show full notes, source layer/block/handle, batch, and confidence. Add batch rollback and revision diffs without losing manual corrections. |

Use side-by-side native CAD and map views during alignment, with optional overlay opacity/blink. Select control points using their original CAD coordinates rather than reverse-transforming already warped preview points. More control points alone do not guarantee a better result; their distribution, correctness, and chosen transformation matter. QGIS provides a useful reference for control-point tables and transformation choices, including the deliberate distortion introduced by TPS. [QGIS georeferencer documentation](https://doc.qgis.org/3.44/en/docs/user_manual/managing_data_source/georeferencer.html)

The default controls are only **29.09 m apart**. In a numerical sensitivity check, moving one target control by 1 m shifts a point 500 CAD units away by **17.17 m**. Controls should cover the drawing and include independent check points. Define the required operational accuracy with survey/as-built evidence; a visually convincing satellite overlay alone does not establish underground asset location.

The minimum durable data additions are an immutable drawing source (file/hash, units, coordinate frame), original entities (handles, layers, block paths, attributes and source geometry), calibration versions, and versioned import sessions/batches. Derived operational features should retain references to their source entities. Store annotations independently with optional pipeline/valve links. For repeated inserts, identify features by drawing revision, insertion path and entity handle, rather than block name alone.

Topology needs an explicit follow-up: `_decompose_paths` joins endpoints only. A branch ending halfway along a long polyline does not split that polyline into a junction. Add endpoint-to-segment snapping and junction review if operational connectivity is required; do not automatically treat every visual crossing as a connected water pipe. Derive flow direction from confirmed network information, rather than CAD vertex order.

**Validation and release checks**

- Existing suite: **20 DXF tests passed**, including the sample analyze/import smoke test, in an isolated database/cache environment.
- Five targeted probe tests reproduced the calibration activation, lost-history, nonlinear reapplication, preview/commit mismatch, and sample import behaviors above. Their passing assertions confirm the defects/measurements, not that the application is correct.
- Additional synthetic geometry probes confirmed TEXT failure, open-curve false closure, MINSERT loss, OCS mirroring, and missing interior-junction splitting.
- Before release, add regressions for those cases; compare preview and persisted geometry from the same immutable session; require unchanged calibration to leave geometry unchanged; verify clear/reset never changes historical transforms; reconcile every selected asset and annotation.
- Confirm which commit and calibration data are deployed. The current checkout already includes closed-loop, curve, block extraction, and longitude-normalization fixes; older deployments may have additional causes of missing lines or misalignment.

The immediate next delivery should be phase 1 plus the preserved-source/calibration foundation for phase 2. That foundation also makes valve/notes import and later alignment corrections reliable.
