import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import type { DocumentRecord } from "../api/types";
import "./Documents.css";

const ACCEPTED_EXTENSIONS = [".txt", ".md", ".pdf"];
const MAX_BYTES = 25 * 1024 * 1024;

function hasAcceptedExtension(name: string): boolean {
  return ACCEPTED_EXTENSIONS.some((ext) => name.toLowerCase().endsWith(ext));
}

export function Documents() {
  const { push } = useToast();
  const [documents, setDocuments] = useState<DocumentRecord[] | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<DocumentRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    const page = await api.listDocuments();
    setDocuments(page.items);
    return page.items;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const items = await refresh();
        if (cancelled) return;
        const unfinished = items.some((d) => d.status === "uploaded" || d.status === "processing");
        pollTimer.current = setTimeout(tick, unfinished ? 2000 : 8000);
      } catch {
        if (!cancelled) pollTimer.current = setTimeout(tick, 8000);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [refresh]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    for (const file of Array.from(files)) {
      if (!hasAcceptedExtension(file.name)) {
        push(`"${file.name}" isn't supported yet — accepted types: .txt, .md, .pdf`);
        continue;
      }
      if (file.size > MAX_BYTES) {
        push("File exceeds the 25 MB limit");
        continue;
      }
      const optimistic: DocumentRecord = {
        id: `optimistic-${crypto.randomUUID()}`,
        originalFilename: file.name,
        byteSize: file.size,
        status: "uploaded",
        failureCode: null,
        createdAt: new Date().toISOString(),
      };
      setDocuments((prev) => [optimistic, ...(prev ?? [])]);
      try {
        await api.uploadDocument(file);
        await refresh();
      } catch (err) {
        setDocuments((prev) => (prev ?? []).filter((d) => d.id !== optimistic.id));
        if (err instanceof ApiError && err.code === "file_too_large") {
          push("File exceeds the 25 MB limit");
        } else if (err instanceof ApiError && err.code === "unsupported_media_type") {
          push(`"${file.name}" isn't supported yet — accepted types: .txt, .md, .pdf`);
        } else {
          push("Upload failed — please try again");
        }
      }
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    const id = pendingDelete.id;
    setDocuments((prev) => (prev ?? []).filter((d) => d.id !== id));
    try {
      await api.deleteDocument(id);
    } catch {
      push("Delete failed — please try again");
      await refresh();
    } finally {
      setDeleting(false);
      setPendingDelete(null);
    }
  }

  const isEmpty = documents !== null && documents.length === 0;

  return (
    <div>
      <div className="documents__header">
        <h1 className="documents__title">Documents</h1>
        <Button onClick={() => fileInputRef.current?.click()}>Upload document</Button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          hidden
          onChange={(e) => {
            void handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      <div
        className={`documents__dropzone ${dragOver ? "documents__dropzone--active" : ""} ${
          documents && documents.length > 0 ? "documents__dropzone--slim" : ""
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          void handleFiles(e.dataTransfer.files);
        }}
      >
        Drag files here, or use Upload document
      </div>

      {documents === null ? (
        <div className="documents__skeleton" aria-busy="true" aria-label="Loading documents">
          {[0, 1, 2].map((i) => (
            <div key={i} className="documents__skeleton-row" />
          ))}
        </div>
      ) : isEmpty ? (
        <EmptyState
          icon="📄"
          title="No documents yet"
          body="Upload a PDF, .txt, or .md file to start chatting with it."
          action={<Button onClick={() => fileInputRef.current?.click()}>Upload document</Button>}
        />
      ) : (
        <ul className="documents__list">
          {documents.map((doc) => (
            <li key={doc.id} className="documents__row">
              <span className="documents__filename" title={doc.originalFilename}>
                {doc.originalFilename}
              </span>
              <span className="documents__size">{(doc.byteSize / 1024).toFixed(0)} KB</span>
              <span className="documents__date">{new Date(doc.createdAt).toLocaleDateString()}</span>
              <StatusBadge status={doc.status} failureCode={doc.failureCode} />
              <button
                type="button"
                className="documents__delete"
                aria-label={`Delete ${doc.originalFilename}`}
                onClick={() => setPendingDelete(doc)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      <Modal
        open={pendingDelete !== null}
        size="sm"
        title="Delete document"
        onClose={() => setPendingDelete(null)}
      >
        <p>
          Delete '{pendingDelete?.originalFilename}'? This removes it and its indexed content. This
          can&apos;t be undone.
        </p>
        <div className="modal__actions">
          <Button variant="secondary" onClick={() => setPendingDelete(null)} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => void confirmDelete()} loading={deleting}>
            Delete
          </Button>
        </div>
      </Modal>
    </div>
  );
}
