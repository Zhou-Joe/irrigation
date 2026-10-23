# AI chat UI review — 2026-10-24

The map's AI assistant now provides an expandable desktop conversation and a phone-sized dialog, with immediate preparation feedback, streamed answers, tool activity, charts, and download cards. This work is on `codex/ai-chat-ui`, based on `33c30a45`. Production deployment is being handled separately by GLM.

## User-visible behavior

- Preparing, using tools, writing, completed, failed, and stopped states have distinct labels and animated shared SVG icons. Reduced-motion preferences disable the animations.
- Each tool invocation has an ID, running/result state, duration, and expandable escaped arguments/output. Repeated same-name calls and reversed completion order remain separate. Finished activity normally collapses.
- Markdown answers support readable headings, lists, scrollable tables, code copying, and response copying. System sans-serif fonts match the rest of the application.
- Generated raster charts appear inline, with download cards for charts, spreadsheets, reports, and other generated files. Cards show filename, type, and size. Repeated file events are deduplicated.
- The composer supports Enter, Shift+Enter, IME composition, auto-height, and stopping reception. Starting a new conversation aborts the prior browser request and ignores stale output.
- Scrolling up pauses following new content; a button returns to the latest message. Error recovery edits the original request instead of automatically repeating actions.
- Mobile dialogs account for safe areas and the visual viewport, use larger touch targets, trap keyboard focus, and close with Escape. Desktop supports a compact docked panel or expanded view.

## Defects corrected

- The old UI had no immediate preparation state, fragile stream parsing, and weak feedback when a connection ended without a completed answer.
- Tool indices restart at zero each model round. The server now emits stable call IDs and preserves simultaneous text/tool chunks, so later calls and parallel results are represented correctly.
- Failed tool results now carry explicit status. Non-object tool JSON cannot break event generation.
- A single generated `file` from tools such as `build_weekly_report` now produces a file event as well as the existing export/Python paths.
- New conversations and aborted requests cannot receive text from an earlier request or have their composer state reset by an earlier request's cleanup.
- The latest-message button resets on a new conversation/request. Textarea sizing allows for fractional line heights, avoiding a small unwanted scrollbar.

## Rendering boundaries

DOMPurify 3.4.17 is vendored from the official npm package, with its license and verified package integrity recorded alongside the asset. Model Markdown uses a strict element/attribute allowlist. Scripts, forms, input elements, event attributes, IDs, classes, and styles are removed. Links require HTTP(S); generated artifact URLs require the same origin and the existing workspace path format. Only raster images are previewed automatically; SVGs remain file links. Tool details use text content.

Stopping means stopping reception in the browser. The UI explicitly says that already-started server operations may still finish; it does not promise to cancel those operations.

## Validation

- Django core suite: **197 tests, 196 passed and 1 skipped**; system checks passed.
- JavaScript regression suite: **42 passed**, including 8 new stream/state/artifact tests.
- New backend tests cover model rounds, repeated chunks, missing IDs, matching failure results, malformed output, report artifacts, and simultaneous text/tool output.
- JavaScript syntax and Git whitespace checks passed.
- Browser checks used a disposable fixture database and synthetic SSE responses, without model calls, live tools, emails, or production data changes. Checked immediate feedback, repeated tool names with reversed completion, inline chart loading, download paths, unsafe Markdown removal, stopping, active-request replacement, and error-to-edit recovery.
- Layouts checked at 320×568, 390×844, 390×500, 768×1024, and expanded desktop widths. No horizontal document overflow; the composer remains inside the resized viewport once its resize event is applied. A real phone keyboard and live model integration still need a device smoke test after deployment.

## Local preview and access

`pm-flow-review` is staff, superuser, and active in the disposable local fixture database. Its password is unchanged. The fixture database has AI disabled and no provider/model settings, so changing the user's role alone did not display its AI button. Both local preview ports **8774** and **8775** now run the synthetic chat preview with a visible **演示** badge. These previews return sample responses and files, without calling a model or real tools. The preview server override and account change are local only, ignored by Git, and are not part of the production application.

## Deployment handoff

Deploy this branch's Django/template/static changes together and collect static assets using the project's usual workflow. New client asset query versions prevent reuse of the previous chat code. No database migration is required. Existing role and configured-provider checks remain in force. The client also accepts older name-only tool events, though the updated server is needed for exact repeated/parallel invocation matching and the additional report file events. No production deployment was performed for this branch.
