# Shanghai-day AI history retention

The operator requested AI chat history for the current day only and explicitly
confirmed that AI-generated Excel files/charts should expire with the chat.

Conversations use their Shanghai creation day and expire at the next local
midnight. Legacy imported dates are reconciled once from the original first
checkpoint, so an import timestamp cannot make an old chat look newly created.
The date boundary is explicit Asia/Shanghai, independent of host/device timezone.

The history API filters today's conversations, while detail/download access
rejects expired or unknown IDs without registering them again. Submitting an old
thread creates a fresh current-day conversation and preserves the newly submitted
question. The client resets the conversation at midnight and refreshes policy on
open/foreground; server-provided time intervals avoid reliance on the phone clock.

Cleanup deletes the expired conversation's checkpoints, pending writes, metadata
and private workspace, including generated attachments. It validates the absolute
workspace target and refuses a redirected workspace root. It does not delete
business records, mail attachments or files already downloaded to a device.
An active expired task is cancelled and deferred until it releases its execution
lease; completion retries cleanup. Ordinary requests trigger throttled cleanup,
and the hourly cron includes midnight and retries even without website traffic.

Validation: 288 isolated Django tests (287 passed, one existing CAD skip), 61 Node
tests passed. Seven initial backend cases cover calendar boundaries, metadata/message/
file cleanup, dry-run preservation, active-task protection, expired access, fresh
cross-day submissions and legacy checkpoint dates. The frontend timestamp test
checks Shanghai midnight using UTC/server timestamps. The portable test runner
now isolates private AI storage as well as database/cache state.

The follow-up orphan-state regression brings the focused AI history suite to eight
passing tests. It verifies that unregistered legacy checkpoint/pending-write state
is removed while registered current-day conversations remain intact.

## Production release

Production was upgraded to `485762b6`, static assets collected, and the
`horticulture` service restarted successfully. Existing cron entries were retained;
the private AI cleanup command now runs hourly at minutes 00 and 05. No database
migration or additional dependency was needed.

Validation against an isolated production copy reconciled legacy checkpoint dates
and removed 26 expired conversations and nine old workspace directories, preserving
the two actual current-day conversations and their files. Four unregistered legacy
QA checkpoint threads were subsequently removed by the orphan-state follow-up.
All 89 non-AI business tables were verified unchanged using full-row hashes.

Live verification at 2026-10-27 00:01 Shanghai time confirmed the actual midnight
rollover: the prior day's remaining conversations, checkpoint rows, pending writes
and private workspace directories were all gone. The history API returned an empty
new-day list with `Cache-Control: no-store`; old conversation access was rejected
without recreating metadata. The 89 business-table hashes still matched the fresh
pre-release backup. The next expiry is 2026-10-28 00:00 Shanghai time.

Consistent database/checkpoint and private-workspace backups, saved cron entries,
candidate validation results and live verification output are retained in the
restricted server directory
`deployment_backups/ai-day-history-20261026/`. These backups are for release recovery;
they are not available through the chat history or attachment endpoints.
