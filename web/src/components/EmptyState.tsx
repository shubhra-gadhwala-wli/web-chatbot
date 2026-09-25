import type { ReactNode } from "react";
import "./EmptyState.css";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, body, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon ? (
        <div className="empty-state__icon" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__body">{body}</p>
      {action}
    </div>
  );
}
