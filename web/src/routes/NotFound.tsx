import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <div style={{ textAlign: "center", padding: "var(--space-8)" }}>
      <p>This resource couldn&apos;t be found.</p>
      <Link to="/documents">Back to Documents</Link>
    </div>
  );
}
