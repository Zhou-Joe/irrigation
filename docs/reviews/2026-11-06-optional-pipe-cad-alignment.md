# Optional map alignment for pipe CAD imports

Release `529dfc6e` makes selecting map alignment points optional for new pipe
CAD imports. In step 3 the user can choose current map placement, adjust its
translation, rotation and uniform scale, and confirm the visible result before
import. The existing independently checked control-point workflow is preserved.
The review explicitly distinguishes manual placement from verified calibration.

Manual placement is stored with its exact transform in the import batch, without
creating or changing a global SiteCalibration. Server conversion uses the same
coefficients as the map preview, with the original CAD coordinates as the source.
Pipes, devices, labels and retained reference geometry share that transform.
Signed preview ownership/file checks still apply. Invalid or out-of-map geometry
is rejected before saving; failed imports remain atomic. Existing batches can
subsequently receive a verified point calibration using their retained source
geometry. Manual placement is not offered as an unchecked batch recalibration.

Validation: 315 Django tests passed with one existing CAD fixture skip; all 76
Node tests passed. Regressions cover exact preview geometry, associated devices
and labels, retained references, invalid parameters, signed preview checks,
later precise recalibration, mode switching, stale coordinate avoidance and
reset when uploading another drawing. The production Python runtime also passed
the 43-test alignment/integrity discovery before rollout.

Production was backed up under
`deployment_backups/optional-pipe-cad-20261106/` before a fast-forward release.
No schema migration was needed. Django checks, static collection and service
restart completed. Post-release verification confirmed that pipe, valve, batch,
calibration and zone tables match their pre-release fingerprints, the production
template renders both modes, public JavaScript matches the release hashes and
the login endpoint returns HTTP 200. Refresh an already-open import page once to
load the versioned scripts.
