import { useState } from "react";
import type { DocumentStatus } from "../api/types";
import "./StatusBadge.css";

const LABEL: Record<DocumentStatus, string> = {
  uploaded: "Uploaded",
  processing: "Processing…",
  ready: "Ready",
  failed: "Failed",
};

const ICON: Record<DocumentStatus, string> = {
  uploaded: "🕐",
  processing: "⟳",
  ready: "✓",
  failed: "!",
};

interface StatusBadgeProps {
  status: DocumentStatus;
  failureCode?: string | null;
}

export function StatusBadge({ status, failureCode }: StatusBadgeProps) {
  const [showReason, setShowReason] = useState(false);

  if (status !== "failed") {
    return (
      <span className={`status-badge status-badge--${status}`}>
        <span className={`status-badge__icon status-badge__icon--${status}`} aria-hidden="true">
          {ICON[status]}
        </span>
        {LABEL[status]}
      </span>
    );
  }

  return (
    <span className="status-badge__wrap">
      <button
        type="button"
        className="status-badge status-badge--failed status-badge--button"
        aria-expanded={showReason}
        onClick={() => setShowReason((v) => !v)}
      >
        <span className="status-badge__icon status-badge__icon--failed" aria-hidden="true">
          {ICON.failed}
        </span>
        {LABEL.failed}
      </button>
      {showReason ? (
        <span className="status-badge__reason" role="status">
          Failed — {failureCode ?? "could not process this document"}
        </span>
      ) : null}
    </span>
  );
}
