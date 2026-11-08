# Location controls and AI workspace fixes

The location-management batch button now uses the same continuous map placement as the main map. Its CSV dialog and single-create page link have been removed from that primary flow. Creation updates pins and results in place, preserving the viewport.

Location editing has a dedicated submit handler with a persistent saving/saved/error button state and a status next to the button. Native validation failures, expired login, permission/not-found responses and request timeouts produce explicit feedback. Form submission uses the action attribute, avoiding named-control shadowing. The shared-location form also uses the action attribute.

Workspace switching no longer writes the AI panel hidden state from account eligibility. AI owns its open/closed state, closes silently on a business change, and moves its mobile launcher to the persistent document before replacing map controls. It reattaches after the new controls mount. Closing also repairs an externally inconsistent hidden/ARIA state, and missing launchers cannot prevent closing.

Changed assets have new version URLs; the service-worker release marker is bumped without automatic page reload. At the user's explicit request, no further test or UI verification was run for this follow-up; acceptance is left to the user.
