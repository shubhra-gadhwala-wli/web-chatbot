import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Citation } from "../api/types";
import "./CitationChip.css";

interface GroupedCitation {
  documentId: string;
  documentName: string;
  locations: { chunkId: string; kind: string; start: number; end: number }[];
}

export function groupCitations(citations: Citation[]): GroupedCitation[] {
  const byDocument = new Map<string, GroupedCitation>();
  for (const c of citations) {
    const existing = byDocument.get(c.documentId);
    const location = { chunkId: c.chunkId, ...c.location };
    if (existing) {
      existing.locations.push(location);
    } else {
      byDocument.set(c.documentId, {
        documentId: c.documentId,
        documentName: c.documentName,
        locations: [location],
      });
    }
  }
  return [...byDocument.values()];
}

function formatLocation(loc: { kind: string; start: number; end: number }): string {
  const prefix = loc.kind === "page" ? "p." : "line ";
  return loc.start === loc.end ? `${prefix}${loc.start}` : `${prefix}${loc.start}-${loc.end}`;
}

// "Source removed" is architecture's safe display for a citation whose
// underlying document was deleted after the answer was generated (404 on
// fetch). It never falls back to showing another account's data.
const REMOVED = Symbol("removed");

export function CitationChip({ group }: { group: GroupedCitation }) {
  const [open, setOpen] = useState(false);
  const [excerpt, setExcerpt] = useState<{ location: string; text: string } | typeof REMOVED | null>(
    null,
  );

  useEffect(() => {
    if (!open || excerpt !== null) return;
    const first = group.locations[0];
    api
      .getChunk(group.documentId, first.chunkId)
      .then((chunk) =>
        setExcerpt({ location: formatLocation(chunk.location), text: chunk.text }),
      )
      .catch(() => setExcerpt(REMOVED));
  }, [open, excerpt, group]);

  if (excerpt === REMOVED) {
    return (
      <span className="citation-chip citation-chip--removed" aria-disabled="true">
        📄 Source removed
      </span>
    );
  }

  return (
    <span className="citation-chip__wrap">
      <button
        type="button"
        className="citation-chip"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        📄 {group.documentName} · {group.locations.map(formatLocation).join(", ")}
      </button>
      {open ? (
        <div className="citation-chip__detail" role="region" aria-label={`Excerpt from ${group.documentName}`}>
          {excerpt === null ? (
            <p>Loading excerpt…</p>
          ) : (
            <>
              <p className="citation-chip__location">
                {group.documentName} · {excerpt.location}
              </p>
              <p className="citation-chip__text">{excerpt.text}</p>
            </>
          )}
        </div>
      ) : null}
    </span>
  );
}
