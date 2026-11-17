# Compact pest work-order fields

Pest form chips, selects, text inputs and remarks use 13px text on desktop and phones. The scoped phone override takes precedence over the shared 16px input rule. Bird names and species codes retain searchable dropdown choices and accept custom text. Suggestions include configured choices and values from the caller's recent visible work orders. Status and building directions retain their existing validation.

New orders record the authenticated submitter and the existing system weather snapshot automatically. These fields have no form controls. Editing preserves the original reporter and weather, including imported history. Observation notes appear in the bottom remark field and save there once; legacy submissions are merged without duplicate text or mixed newline sequences. Original historical source rows remain intact.

Validation: 128 operations regressions, 112 JavaScript tests and the final 22-test field suite passed. Browser exercises at 390px and 1280px verified 13px controls, dropdown pointer/keyboard selection, custom entries, subsequent suggestions, new submissions, edits, hidden automatic fields and combined remarks. Screenshots use an isolated database with synthetic fixtures. No schema migration or data backfill is needed.
