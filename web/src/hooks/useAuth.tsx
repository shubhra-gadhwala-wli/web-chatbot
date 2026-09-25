import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Account } from "../api/types";

interface AuthState {
  account: Account | null;
  status: "loading" | "authenticated" | "unauthenticated";
  register: (email: string, password: string) => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((acc) => {
        if (!cancelled) {
          setAccount(acc);
          setStatus("authenticated");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAccount(null);
          setStatus("unauthenticated");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const acc = await api.register(email, password);
    setAccount(acc);
    setStatus("authenticated");
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const acc = await api.login(email, password);
    setAccount(acc);
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) {
        throw err;
      }
    }
    setAccount(null);
    setStatus("unauthenticated");
  }, []);

  return (
    <AuthContext.Provider value={{ account, status, register, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
