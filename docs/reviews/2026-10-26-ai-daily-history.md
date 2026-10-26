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
tests passed. Seven new backend cases cover calendar boundaries, metadata/message/
file cleanup, dry-run preservation, active-task protection, expired access, fresh
cross-day submissions and legacy checkpoint dates. The frontend timestamp test
checks Shanghai midnight using UTC/server timestamps. The portable test runner
now isolates private AI storage as well as database/cache state.

Production-copy validation and deployment outcomes will be recorded when complete.
