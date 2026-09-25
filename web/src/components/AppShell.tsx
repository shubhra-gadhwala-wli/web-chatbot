import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import "./AppShell.css";

export function AppShell() {
  const { logout } = useAuth();

  return (
    <div className="app-shell">
      <header className="app-shell__nav">
        <span className="app-shell__brand">RAG Chat</span>
        <nav className="app-shell__tabs" aria-label="Primary">
          <NavLink to="/documents" className={({ isActive }) => (isActive ? "is-active" : "")}>
            Documents
          </NavLink>
          <NavLink to="/conversations" className={({ isActive }) => (isActive ? "is-active" : "")}>
            Chats
          </NavLink>
        </nav>
        <button type="button" className="app-shell__logout" onClick={() => void logout()}>
          Logout
        </button>
      </header>
      <main className="app-shell__main">
        <Outlet />
      </main>
    </div>
  );
}
