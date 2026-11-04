# Irrigation shortcuts, difficult-issue mail and CAD binding controls

The irrigation query adds 3/7/14/30-day shortcuts alongside the existing 24-hour
choice. Each click resolves the latest successful sync on the server and keeps
the selected CCU. Returned exact Shanghai-time bounds drive runtime, sensors,
heatmaps and exports. Manual date edits clear the selected shortcut. The preset
group spans the full filter grid and wraps into two columns on small screens.
Unsupported ranges receive HTTP 400; explicit dates remain authoritative.

The email report registry now includes `difficult_workorders`. Its Excel includes
a summary, ongoing issues, issues awaiting confirmation, completed issues updated
in the selected period, and follow-up details. Current unresolved roots remain
visible regardless of their original date; child follow-ups are not counted as
separate issues. Administrative exports also retain flagged PM reports. Workbook
text is stored as text, including descriptions beginning with `=`. Existing
per-report date controls and the scheduled/interactive/API builders share this
new option. Migration 0136 updates the choice state only (SQL no-op).

The zone DXF importer initially hides existing reference polygons and labels.
A checkbox restores them together, as noninteractive references. Explicit
`整体平移` / `绑定勿动` controls default to locked binding mode. CAD movement needs
an explicit unlock and a six-pixel drag. Cancelling movement restores the draft;
anchor picking, binding requests and completed assignments lock movement. After
one zone is assigned, the remaining batch and reset control stay locked, keeping
them aligned with geometry already saved. Re-upload resets draft-only state.

Validation: 306 Django tests passed with one existing CAD fixture skip; all 72
Node tests passed. Focused CAD gesture tests also pass after the in-flight
binding lock was added. Tests cover all sync windows/failure/manual overrides,
old unresolved issues, child deduplication, attachments without SMTP, hidden
reference labels, cancelled movement and attempted movement during/after binding.
Browser checks use synthetic data and a disposable SQLite database. They verify
7/30-day selection, retained CCU, CAD upload, explicit modes and the disabled
movement control after assigning the first zone. No production zone edits are
part of this release.

## Production release

Pending candidate verification and deployment. The existing active `每日推送`
configuration (id 2, daily at 09:00) will receive the new attachment with the
existing work-report date window. Its recipients, schedule and other selected
reports will be preserved; no immediate test email will be sent.
