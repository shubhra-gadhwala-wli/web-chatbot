## Product scope published; downstream handoff active

- Published the v1 [release scope](/WLI/issues/WLI-10#document-release-scope-v1), mapping all R1–R15 to testable Given/When/Then criteria, explicit deferred scope, P0/P1/P2 ordering, risks, and product defaults.
- **In scope:** local multi-user isolated document RAG; PDF/`.txt`/`.md` up to 25 MB; cited/no-context text chat; persisted named conversations; Chrome-first optional browser voice.
- **Explicitly out:** cloud/production deployment, sharing/admin, OCR and other formats, general chat, streaming, deletion/export/recovery flows, and cross-browser/offline voice guarantees.
- **First vertical slice:** “Private cited answer from one `.txt` document” (auth/isolation → upload → local ingest → citation or explicit no-context result).
- Handed Design to [WLI-11](/WLI/issues/WLI-11) (UX) and feasibility/first-slice architecture to [WLI-12](/WLI/issues/WLI-12) (Architect). Both include source links to the scope, [WLI-8](/WLI/issues/WLI-8), and [WLI-9](/WLI/issues/WLI-9).

**Next action / owner:** UX completes the design handoff and Architect confirms first-slice feasibility. This issue is blocked on those child deliverables; PM will then obtain the QAFunctional testability confirmation before the Product stage closes.
