## Architecture handoff — local-first RAG voice chatbot v1

**Status:** ready to start

Produce the technical architecture and first-slice build breakdown for the parent’s [release scope](/WLI/issues/WLI-10#document-release-scope-v1). Source detail: [requirements draft](/WLI/issues/WLI-8#document-requirements-draft) and [research brief](/WLI/issues/WLI-9#document-artifact-review-ee5e8461-4258-42e8-a978-f8030d8769b7).

Validate feasibility of the named thin vertical slice: **Private cited answer from one `.txt` document** — authentication and account isolation → upload → local extraction/chunk/embed/vector persistence → non-streaming grounded answer with a document/chunk citation or explicit no-context response — running locally end to end.

Architecture decisions required:

- Local data/schema and authorization approach that prevents all cross-account document, vector, conversation, and citation access.
- Secure password/session approach supporting the 14-day product session default; configuration handling that uses YAML plus `.sample.env`, never real committed secrets.
- Configurable OpenAI-compatible LLM endpoint (optional OpenAI key default) and fully-local endpoint compatibility; vector store remains local/embedded.
- PDF/`.txt`/`.md` ingestion, extraction/chunking/embedding choices, 25 MB validation, status transitions, failure reason, cancellation/deletion cleanup, and no in-place retry.
- Retrieval/generation boundary that produces source document and chunk/location citations, declines unsupported/no-context answers, and specifies error behavior.
- Persistent named conversation model, non-streaming pending state, and Chrome browser-native STT/TTS boundaries/fallbacks.
- Local developer run/deployment path and an implementable first-slice task decomposition with interfaces/contracts.

Constraints: local-only v1; no cloud deployment, sharing, admin, OCR, non-grounded chat, streaming, account/conversation deletion, or browser-voice parity. Do not select an unvalidated component purely from the research shortlist; document rationale and trade-offs.

Deliverable: architecture issue document(s) including ADRs as needed, data/API boundaries, threat/isolation controls, feasibility verdict for the first slice, and buildable child tasks/dependencies. Flag any scope-threatening infeasibility on this issue, otherwise mark it done after the handoff; do not wait for parent comments.

Acceptance: the first vertical slice is explicitly feasible or has a concrete blocker/alternative, and development can be sequenced without reopening product scope.
