## Design handoff — local-first RAG voice chatbot v1

**Status:** ready to start

Create the UX/UI flow and wireframes for the v1 scope in the parent’s [release scope](/WLI/issues/WLI-10#document-release-scope-v1). Source detail: [requirements draft](/WLI/issues/WLI-8#document-requirements-draft) and [research brief](/WLI/issues/WLI-9#document-artifact-review-ee5e8461-4258-42e8-a978-f8030d8769b7).

Design the following flows and all named success, loading, empty, unsupported, and error states:

- Registration, login, logout, persistent-session return, and access-denied behavior.
- Strict per-user document library: PDF/`.txt`/`.md` upload (25 MB maximum), `uploaded`/`processing`/`ready`/`failed` status, unsupported/oversize feedback, and confirm-delete.
- Non-streaming text chat: visible pending state, grounded answer with clear document plus chunk/location citation, no-documents and no-relevant-context responses.
- Multiple persisted named conversations: new, switch, rename, retained history.
- Chrome-first optional voice: start/transcript/error/retry, SpeechRecognition unsupported/permission-denied state, TTS trigger and mute/off state. Text chat must remain fully usable outside supported browsers.

Constraints: local-only app; no sharing/admin/cloud flows; English v1; voice is a convenience layer and must not obscure citations or the text fallback. Do not introduce out-of-scope flows from the source scope.

Deliverable: an issue document with IA, user flows/wireframes, state inventory, citation presentation guidance, and an implementation-ready handoff. Record any product ambiguity on this issue and mark it done when the handoff is complete; do not wait for parent comments.

Acceptance: a frontend engineer can implement each in-scope requirement’s UI behavior and all above states from the document without inferring a new product policy.
