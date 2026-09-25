import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { ToastProvider } from "./components/Toast";
import { AuthProvider } from "./hooks/useAuth";
import { Register } from "./routes/Register";
import { Login } from "./routes/Login";
import { Documents } from "./routes/Documents";
import { Conversations } from "./routes/Conversations";
import { ConversationView } from "./routes/ConversationView";
import { NotFound } from "./routes/NotFound";

function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/register" element={<Register />} />
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <ProtectedRoute>
                  <AppShell />
                </ProtectedRoute>
              }
            >
              <Route path="/documents" element={<Documents />} />
              <Route path="/conversations" element={<Conversations />} />
              <Route path="/conversations/:conversationId" element={<ConversationView />} />
            </Route>
            <Route path="/" element={<Navigate to="/documents" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
