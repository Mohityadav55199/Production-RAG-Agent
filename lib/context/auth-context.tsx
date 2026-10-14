"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  UNAUTHORIZED_EVENT,
  apiFetch,
  clearToken,
  getToken,
  setToken,
} from "@/lib/api/client";

export interface AuthUser {
  id: string;
  email: string;
  is_admin?: boolean;
}

// A token the server issues after each successful login. Sending it back on the next login marks this
// browser as the owner's usual device, so someone guessing the password elsewhere can never lock them out.
const DEVICE_KEY = "rag_device";

function getDevice(): string | undefined {
  try {
    return localStorage.getItem(DEVICE_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

function setDevice(token: string | undefined) {
  if (!token) return;
  try {
    localStorage.setItem(DEVICE_KEY, token);
  } catch {
    // storage blocked: logins still work, just without the lockout protection
  }
}

/**
 * loading      checking a stored session
 * waking       the server did not answer yet (free hosting sleeps when idle); retrying
 * unreachable  retries exhausted; the stored session is kept so the user can retry
 */
export type AuthStatus = "loading" | "waking" | "authed" | "anon" | "unreachable";

interface AuthContextValue {
  user: AuthUser | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => void;
  retry: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthResponse {
  token: string;
  device?: string;
  user: AuthUser;
}

const WAKE_RETRY_DELAY_MS = 5000;
const WAKE_GIVE_UP_MS = 120_000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [attempt, setAttempt] = useState(0);
  const runId = useRef(0);
  const invalidateRuns = useCallback(() => {
    runId.current++;
  }, []);

  // Validate a stored token on load. Only a 401 means "not logged in"; timeouts and 5xx while the
  // server wakes up are retried, and never discard a valid session.
  useEffect(() => {
    const id = ++runId.current;
    const current = () => id === runId.current;

    if (!getToken()) {
      setStatus("anon");
      return;
    }

    (async () => {
      const startedAt = Date.now();
      setStatus("loading");
      while (current()) {
        try {
          const me = await apiFetch<AuthUser>("/auth/me", { timeout: 20000 });
          if (!current()) return;
          setUser(me);
          setStatus("authed");
          return;
        } catch (err) {
          if (!current()) return;
          if (err instanceof ApiError && err.status === 401) {
            clearToken();
            setUser(null);
            setStatus("anon");
            return;
          }
          if (Date.now() - startedAt > WAKE_GIVE_UP_MS) {
            setStatus("unreachable");
            return;
          }
          setStatus("waking");
          await sleep(WAKE_RETRY_DELAY_MS);
        }
      }
    })();

    return invalidateRuns;
  }, [attempt, invalidateRuns]);

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
      body: JSON.stringify({ email, password, device: getDevice() }),
      timeout: 60000, // a sleeping server can take a while to answer the first request
    });
    setToken(data.token);
    setDevice(data.device);
    setUser(data.user);
    setStatus("authed");
  }, []);

  const login = useCallback((email: string, password: string) => authenticate("/auth/login", email, password), [authenticate]);
  const signup = useCallback((email: string, password: string) => authenticate("/auth/signup", email, password), [authenticate]);

  const logout = useCallback(() => {
    invalidateRuns();
    clearToken();
    try {
      // Per-browser UI state that belongs to the previous user
      localStorage.removeItem("rag-active-collection");
    } catch {
      // ignore
    }
    setUser(null);
    setStatus("anon");
  }, [invalidateRuns]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const value = useMemo(
    () => ({ user, status, login, signup, logout, retry }),
    [user, status, login, signup, logout, retry]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
