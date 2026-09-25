import { describe, expect, it } from "vitest";
import { groupCitations } from "./CitationChip";
import type { Citation } from "../api/types";

describe("groupCitations", () => {
  it("collapses multiple citations from the same document into one group", () => {
    const citations: Citation[] = [
      {
        documentId: "doc1",
        documentName: "notes.txt",
        chunkId: "chunk1",
        location: { kind: "line", start: 1, end: 5 },
      },
      {
        documentId: "doc1",
        documentName: "notes.txt",
        chunkId: "chunk2",
        location: { kind: "line", start: 20, end: 25 },
      },
      {
        documentId: "doc2",
        documentName: "other.pdf",
        chunkId: "chunk3",
        location: { kind: "page", start: 3, end: 3 },
      },
    ];

    const groups = groupCitations(citations);

    expect(groups).toHaveLength(2);
    expect(groups[0].documentId).toBe("doc1");
    expect(groups[0].locations).toHaveLength(2);
    expect(groups[1].documentId).toBe("doc2");
    expect(groups[1].locations).toHaveLength(1);
  });

  it("returns an empty list for no citations (no_relevant_context / no_documents)", () => {
    expect(groupCitations([])).toEqual([]);
  });
});
