# Feedback attachments, deletion and completion status

Feedback accepts other files alongside the existing photo picker. Each ordinary attachment can be up to 50 MB; photos retain the 5-photo/10 MB limits. Photos and ordinary attachments together are limited to 10 files and 100 MB. Users can remove a selected file before submitting and download stored attachments using their original names.

New and existing feedback starts as 未完成. The author, an administrator for the feedback's team, or a global administrator can switch between 未完成 and 已完成, remove individual photos/files, and delete the feedback with confirmation. Other team members keep read access. Cross-team visibility remains limited to global administrators. Changes are audited and enforce POST, CSRF and the active team context.

Files remain outside public media and static directories. Ordinary files are served as authenticated downloads with a fixed binary content type. Database failures clean staged uploads; deletion removes files only after the transaction commits. Feedback deletion preserves a tombstone for duplicate-submission protection while removing the attachments and the entry from the board.

Migration `0011_feedback_attachments_status` adds two feedback fields and the attachment table. The status has a database default so the previous application version can still create feedback during a code rollback. Existing messages, photos and attribution are preserved.

Validation: 141 operations tests, 115 JavaScript tests and the final 18-test feedback suite passed; no migration drift. Browser checks at 390px and 1280px covered mixed uploads, removing pending files, downloads with original filenames, both status transitions, author/peer/admin controls, individual file/photo removal, confirmed feedback deletion and updated counts. Screenshots and fixtures use an isolated temporary database.
