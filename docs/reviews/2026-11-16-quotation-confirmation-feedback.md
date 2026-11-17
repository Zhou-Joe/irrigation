# EnGenie quotation confirmation and team feedback

## Result

EnGenie previously instructed users that only the quotation card button could save a quote. A confirmation typed in chat had no save action. Explicit chat confirmations such as `确认写入`, `确认保存报价` and `confirm quotation` now submit the reviewed card through the existing quotation-confirmation endpoint. The reply comes from the persisted save receipt and is retained in conversation history. No extra model call is needed to announce a successful save.

The action keeps the existing manager permission, signed draft, ownership, CSRF protection, validation and submission key. Unresolved fields remain visible for correction. Multiple pending vendor quotes require choosing a specific card. Negated statements and questions do not submit; repeated confirmations reuse the saved receipt. Uploading another attachment does not confirm a previous quote. Vendor quotes continue to add historical price records; the current reference-price selection is not silently changed.

The new `/feedback/` page has one message field and optional photos, with no separate feedback/feature-request type. Navigation is available in the top bar, mobile menu and PWA launcher for both businesses. Each submission is attributed to the active team on the server. Staff/platform administrators can review and filter all teams; other members see their current team's feedback. Photos are privately served through the same team checks.

Up to five photos of 10 MB each are accepted. Images are decoded, oriented and resized to at most 1920 pixels before storage, and served as JPEG. Validation failure does not leave a partial feedback record. A submission key prevents accidental duplicates after a repeated POST. Changing team context while a form is open requires refreshing before submission.

## Validation

- 32 focused Django tests passed: quotation save/receipt/history, daily AI history, feedback and operations administration.
- All 94 JavaScript tests passed, including explicit/negative confirmation, cross-conversation cards, multiple pending quotes, missing fields, uncertain outcomes and receipt reuse.
- DOM integration with the real Django quotation endpoint passed: a typed confirmation created one price record; repeating it made no extra save request. Missing required fields prevented submission. Feedback character counts and photo previews were exercised.
- The real LangGraph history update was verified offline with an in-memory checkpointer.
- Migration drift check, Django system checks, Python parsing, JavaScript syntax and git whitespace checks passed.
- Full available-branch suite: 393 executed, 24 assertion failures, 4 errors, 1 skip. Untouched base: 382 executed with the exact same 24 failures/4 errors and skip. The additional 11 tests pass; no new failure names were introduced. Existing failures concern older CAD contracts, Maxicom/weather fixtures, email mocks, operations expectations and a missing local work-item specification.
- Chromium could not launch in this environment because its profile socket was denied, so no rendered-browser screenshot or responsive visual sign-off is claimed. The functional DOM/database integration and Django template rendering were checked.

## Source and rollout

The earlier Windows workspace and its unpushed November 14 changes are unavailable in this session. These changes are based on the latest accessible remote branch, `codex/multi-team-foundation` at `f7e9b6cc821c4fa4d5551267e767d2b04a4a9124`. That is the proposed integration base rather than the older `main`. Integrate with any newer local work before deployment; this patch does not recreate the earlier local review fixes.

The user authorized publishing these changes to a dedicated GitHub branch on November 16. Production deployment remains pending.

Apply migration `operations.0007_team_feedback`, run `collectstatic`, and restart the application during deployment. Photo storage defaults to `internal_server/private_feedback/`; `FEEDBACK_PRIVATE_ROOT` can point to persistent private storage outside media/static directories. Include that storage in backups. Flutter is unchanged. No production database, live quote, email delivery or deployment was changed during verification.
