"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  UNAUTHORIZED_EVENT,
  apiFetch,
  clearToken,
  getToken,
  setToken,
} from "@/lib/api/client";

export interface AuthUser {
  id: string;
  email: string;
}

type AuthStatus = "loading" | "authed" | "anon";

interface AuthContextValue {
  user: AuthUser | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthResponse {
  token: string;
  user: AuthUser;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  // Validate a stored token on first load
  useEffect(() => {
    let cancelled = false;
    if (!getToken()) {
      setStatus("anon");
      return;
    }
    apiFetch<AuthUser>("/auth/me")
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("authed");
      })
      .catch((err) => {
        if (cancelled) return;
        // A 401 already cleared the token. Network errors keep it so a reload can retry.
        if (err?.status === 401) clearToken();
        setUser(null);
        setStatus("anon");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Any API call that comes back 401 ends the session everywhere
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setStatus("anon");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const authenticate = useCallback(async (path: string, email: string, password: string) => {
    const data = await apiFetch<AuthResponse>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      timeout: 30000,
    });
    setToken(data.token);
    setUser(data.user);
    setStatus("authed");
  }, []);

  const login = useCallback((email: string, password: string) => authenticate("/auth/login", email, password), [authenticate]);
  const signup = useCallback((email: string, password: string) => authenticate("/auth/signup", email, password), [authenticate]);

  const logout = useCallback(() => {
    clearToken();
    try {
      // Per-browser UI state that belongs to the previous user
      localStorage.removeItem("rag-active-collection");
    } catch {
      // ignore
    }
    setUser(null);
    setStatus("anon");
  }, []);

  const value = useMemo(
    () => ({ user, status, login, signup, logout }),
    [user, status, login, signup, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
