# Pest history, building parameters and field attachments

## Behavior

Historical bird observations can be imported from a private, validated JSON manifest with relative image/video files. The command defaults to a dry run. Applying creates team-owned location hierarchies, extends a versioned work catalog with an observation leaf, and preserves source rows, original cells, observation values and media provenance. Existing work content is retained. Source identifiers prevent duplicate imports; changed records require reconciliation instead of overwriting old work.

Historical observation dates and times are distinct from work start/end times. Missing attendance, labor hours, bird status and treatment outcomes remain unknown. An inactive source placeholder does not impersonate a real worker. The historical source panel continues to show the original discovery date after a work-order edit. The imported-history filter covers older years, and filtering a building includes its visible child locations.

Work branches define typed observation fields. Building definitions supply building-specific choices such as impact direction; child floors and rooms inherit them. Only the selected work branch's requested fields are shown. The server validates values against current team-visible definitions and snapshots labels and values on each submitted record. Previous unchanged choice values remain usable when editing historical records. Manager forms maintain definitions, and catalog revisions preserve them.

Pest work-order submit/edit forms now accept images and videos, show previews, preserve existing attachments and support explicit removal. Files are served through report/team/worker access checks outside public media/static storage. Video playback supports bounded range and HEAD requests. Replayed submissions do not create duplicate files; rollback cleans unattached files, while an old-file cleanup error does not remove a committed replacement.

## Limits and rollout

Work orders support up to 10 attachments, 50 MB per file and 100 MB per submission. The historical importer also caps total batch media at 100 MB and checks counts, declared sizes and filesystem sizes before loading any attachment. It validates hashes and paths before writing, and applies one preflight under the team transaction lock.

Apply migrations `operations.0008_work_parameters` and `operations.0009_pest_history` after their existing `0007_team_feedback` dependency, then collect static assets and restart the application. `PEST_WORKORDER_PRIVATE_ROOT` must be persistent, writable by the service and outside public media/static directories. Back up the database and private attachments. User-supplied manifests and photos are private deployment inputs; generated outputs are ignored by git.

From `internal_server`, validate the private import before applying:

```sh
python manage.py import_pest_history /private/path/manifest.json --team pest-control
python manage.py import_pest_history /private/path/manifest.json --team pest-control --apply
```

Use the actual destination team code. A code rollback should retain additive history tables and private media so new observations are preserved. Production access remains pending; verification used an isolated database.

## Validation

- 49 focused Django tests pass across history import/views, parameters, media, quotation confirmation and AI history.
- All 100 JavaScript tests pass. Real DOM exercises cover parameter changes across buildings/work branches and image/video previews with cleanup.
- The supplied source was checked against its workbook digest and every extracted media byte. An isolated import and repeat import verified record/photo/location counts, zero duplicate records, unknown labor values, private media responses and no irrigation records.
- Migration drift and Django system checks are clean; git whitespace checks pass.
- A broader 112-test operations/AI run has the same six pre-existing failure names as the untouched branch baseline, with no newly failing names. These concern older sharing/map/user-management expectations. The later focused run includes the additional validation-limit regressions.
- No rendered-browser visual sign-off is claimed; template, DOM and real Django/database/media flows were exercised.
