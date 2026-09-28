# Release Scope — Local-First RAG Voice Chatbot v1

**Owner:** PM · **Inputs:** WLI-8 Requirements Draft; WLI-9 Research Brief; locked intake decisions in WLI-4 · **Status:** ready for Design and Architecture

## Product outcome and release boundary

**Jobs-to-Be-Done:** A registered user needs to privately upload a small set of personal documents on their own machine and ask questions of those documents, receiving a cited answer or a truthful no-context response. Voice is an optional convenience layer over that trusted text experience.

This is a locally deployed, multi-user web application. Accounts, documents, vectors, and conversations are strictly isolated by account. The application, its data store, files, and vector store run locally; generation uses a configurable OpenAI-compatible endpoint, defaulting to an optional OpenAI API key. A fully local endpoint such as Ollama is supported by configuration. No real secrets belong in source control or this document.

## In-scope requirements and acceptance criteria

### P0 — Core trustworthy RAG

1. **R1 — Register.** Given an anonymous visitor supplies an unused email and a password that meets the configured policy, when they submit registration, then the account is created, an authenticated session starts, and they arrive at the app home. Given a duplicate email or invalid password, when submitted, then no account is created and a clear validation error is displayed.
2. **R2 — Log in.** Given a registered user submits valid credentials, when they log in, then they reach their own app home. Given invalid credentials, when submitted, then access is denied with a generic invalid-credentials error.
3. **R3 — Log out.** Given an authenticated user, when they log out, then the session is invalidated, they return to login, and the old session cannot access protected routes.
4. **R4 — Persistent session.** Given a user returns within the v1 14-day session window, when they reopen the browser, then they remain signed in; after expiry, protected routes require login.
5. **R5 — Upload.** Given an authenticated user selects PDF, `.txt`, or `.md` files no larger than 25 MB each, when upload completes, then a record is created in `uploaded` state. Given another type or an oversize file, when upload is attempted, then it is rejected before processing with a clear reason and no partial record.
6. **R6 — Local ingestion.** Given an uploaded document, when processing runs, then text is extracted, chunked, embedded, and stored in the local embedded vector store before the document becomes `ready`. Given extraction or embedding fails, when processing ends, then it becomes `failed` with a visible reason and is excluded from retrieval.
7. **R7 — Document library/status.** Given an authenticated user opens their library, when document states change, then they can see only their own filename, upload date, size, and `uploaded`/`processing`/`ready`/`failed` status without manually reloading the page.
8. **R8 — Delete document.** Given a user deletes their ready or failed document, when they confirm deletion, then the original file, extracted text, and associated vectors are removed and cannot support future retrieval. Given they delete a processing document, when confirmed, then processing is cancelled/discarded and no partial vectors persist.
9. **R9 — Grounded text chat and citations.** Given a user has one or more ready documents, when they submit a text question, then the answer is grounded in retrieved chunks from their documents and displays a source reference identifying the supporting document and chunk/location. Given no ready document or no relevant support is found, when they submit a question, then the app gives an explicit no-documents/no-relevant-context response rather than an unsupported answer.
10. **R12 — Response state.** Given a user submits a text question, when generation is pending, then the UI visibly indicates progress; when complete, then it presents the complete answer and its citations as one response (non-streaming v1).

### P1 — Retained, navigable conversations

11. **R13 — In-conversation history.** Given a user sends several messages in a conversation, when each answer completes, then questions and answers remain visible in chronological order.
12. **R14 — Persisted named conversations.** Given a user logs out or closes the browser, when they next log in, then their prior named conversations and messages are available, while another account cannot view them.
13. **R15 — Create, switch, and rename conversations.** Given an authenticated user, when they create a conversation, then it starts with no prior message context and is saved with a default name. When they switch to or rename a saved conversation, then the selected/history/name change is retained and the former conversation remains available.

### P2 — Optional Chrome-first voice layer

14. **R10 — Voice input.** Given Chrome/Chromium exposes browser SpeechRecognition and the user permits the microphone, when they activate voice input and speak, then a visible transcript becomes the text message used by R9. Given the API is unsupported, permission is refused, or recognition fails, when that condition occurs, then the control is hidden/disabled or shows a clear retryable error and text chat remains usable.
15. **R11 — Voice output.** Given a response is available and voice output is enabled, when the user triggers playback, then browser-native SpeechSynthesis reads it aloud. Given the user disables/mutes playback, when a response arrives, then it remains text-only.

## Priority and milestones

1. **First thin vertical slice — “Private cited answer from one `.txt` document.”** Register/login, per-account isolation, upload one supported `.txt` document, local ingestion through `ready`, and a non-streaming text question that returns either a citation or an explicit no-context result. It traverses UI → API → local data/vector store → local run path.
2. **P0 completion — Trusted document library.** Extend the slice to PDF and Markdown, all status/error/deletion paths, 25 MB validation, and citation behavior across ready documents.
3. **P1 — Conversations.** Persistent multiple named conversations; create, switch, rename, and retained history.
4. **P2 — Voice.** Layer Chrome-first browser STT/TTS and all unsupported/error/toggle states on the existing text chat.

This ordering applies the **Thin vertical slice** and **Riskiest assumption first** lenses: private grounded retrieval with sources must work before convenience voice; P2 is a Kano performance feature, not a must-have.

## Product defaults resolving WLI-8 open questions

- Account identifier is email; auth uses a persistent 14-day session. Architecture owns the secure mechanism and password-policy implementation.
- Assistant replies are blocking/non-streaming for v1, with a visible pending state.
- Failed ingest has no in-place retry in v1; the user deletes and re-uploads. This prevents ambiguous partial-index behavior.
- The document library refreshes status automatically; Architecture may choose polling or push.
- Chat stays available with zero ready documents but returns the explicit no-documents result; it never becomes general, ungrounded chat.
- Conversation deletion is deferred. Retention is local and persists until the user deletes a document or the local installation/data is removed; account deletion is not included.
- English is the v1 UI and voice default. No performance SLA is promised beyond an interactive local experience for small personal libraries.

## Explicitly out of scope / deferred

- Cloud deployment, managed hosting, external user accounts, collaboration/sharing, roles/admin/moderation, and cross-account search.
- File formats other than PDF, `.txt`, `.md`; OCR/scanned-image PDF support; files over 25 MB; bulk import and re-embedding controls.
- General non-grounded chat, answer guarantees beyond cited retrieved support, model fine-tuning, and sophisticated evaluation/analytics.
- Streaming tokens, conversation deletion/export, account deletion/recovery, cloud sync/backup, and data migration.
- Cross-browser voice parity, offline guarantee for browser speech recognition, external STT/TTS services, and mobile-specific voice UX.
- Accessibility certification, localization beyond English, formal scale/performance/availability SLA, billing, telemetry, and production deployment.

## Risks and assumptions

| Risk | Assumption / mitigation |
|---|---|
| Browser recognition may be unavailable or may use a browser/provider service | Chrome-only voice is accepted; text remains a full fallback. Do not represent STT as guaranteed offline. |
| External configured LLM can receive retrieved context | The user deliberately configures its endpoint/key; document/vector persistence remains local. Architecture must make the endpoint boundary clear. |
| Local extraction/embedding can fail on malformed or scanned PDFs | `failed` state, visible reason, exclusion from retrieval, and delete/re-upload fallback are mandatory. |
| Per-account isolation errors expose sensitive documents | Namespace/query authorization must be enforced end-to-end; this is a release-blocking test area. |
| Small local-machine scope may not meet larger-library expectations | v1 assumes low tens of documents and 25 MB per file; capacity growth is a later decision. |

## Open decisions

| Decision | Owner | Needed by |
|---|---|---|
| Secure session, password policy, local account/data schema, authorization enforcement | Architect (with SecurityArchitect as needed) | Before development task breakdown |
| Provider/base-URL configuration contract, embedding/extraction components, and status-update mechanism | Architect | Before development task breakdown |
| Navigation, document/status/error states, citation presentation, and voice unsupported-state flow | UX | Before frontend implementation |
| Test strategy for isolation, state transitions, citations/no-context, and browser fallbacks | QAFunctional | Before QA planning / development completion |

## Traceability and release gate

All in-scope requirements map 1:1 to WLI-8 R1–R15. Development work may enter only with these acceptance criteria intact (**Definition of Ready**). Release requires QA evidence that every applicable criterion passes and that P0 isolation/citation/no-context paths have no release-blocking defect (**Definition of Done**).

**Scope decision:** P0/P1/P2 are in the v1 release; deferred items above are explicitly not promises. The scope–time–quality triangle is held on quality and local-only scope; optional P2 voice is the first candidate to defer if feasibility threatens the core trusted text experience.
