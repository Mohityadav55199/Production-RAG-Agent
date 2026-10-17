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
import { getApiBase } from "@/lib/api/client";

interface ServerStatusContextValue {
  isActive: boolean | null;
  isWaking: boolean;
  isChecking: boolean;
  elapsedSeconds: number;
  justWokeUp: boolean;
  error: string | null;
  checkNow: () => Promise<void>;
}

const ServerStatusContext = createContext<ServerStatusContextValue | null>(null);

const SLOW_THRESHOLD_MS = 2500;
const RETRY_INTERVAL_MS = 3500;
const BACKGROUND_POLL_MS = 45000;

export function ServerStatusProvider({ children }: { children: ReactNode }) {
  const [isActive, setIsActive] = useState<boolean | null>(null);
  const [isWaking, setIsWaking] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [justWokeUp, setJustWokeUp] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wakingRef = useRef(false);

  useEffect(() => {
    wakingRef.current = isWaking;
  }, [isWaking]);

  const wakingStartTimeRef = useRef<number | null>(null);

  const checkHealth = useCallback(async () => {
    setIsChecking(true);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);

    const slowTimer = setTimeout(() => {
      if (!wakingRef.current) {
        setIsWaking(true);
        if (!wakingStartTimeRef.current) {
          wakingStartTimeRef.current = Date.now();
        }
      }
    }, SLOW_THRESHOLD_MS);

    try {
      const apiBase = getApiBase();
      const res = await fetch(`${apiBase}/health`, {
        cache: "no-store",
        signal: controller.signal,
      });

      clearTimeout(slowTimer);
      clearTimeout(timeoutId);

      if (res.ok) {
        if (wakingRef.current) {
          setJustWokeUp(true);
          setTimeout(() => setJustWokeUp(false), 3500);
        }
        setIsActive(true);
        setIsWaking(false);
        wakingStartTimeRef.current = null;
        setElapsedSeconds(0);
        setError(null);
      } else {
        setIsActive(false);
        setIsWaking(true);
        if (!wakingStartTimeRef.current) {
          wakingStartTimeRef.current = Date.now();
        }
        setError(`Status ${res.status}: ${res.statusText || "Server starting"}`);
      }
    } catch (err: unknown) {
      clearTimeout(slowTimer);
      clearTimeout(timeoutId);
      setIsActive(false);
      setIsWaking(true);
      if (!wakingStartTimeRef.current) {
        wakingStartTimeRef.current = Date.now();
      }
      const msg = err instanceof Error ? err.message : "Server unreachable";
      setError(msg);
    } finally {
      setIsChecking(false);
    }
  }, []);

  // Timer for elapsed seconds while waking
  useEffect(() => {
    if (!isWaking) return;
    const interval = setInterval(() => {
      if (wakingStartTimeRef.current) {
        setElapsedSeconds(
          Math.max(1, Math.floor((Date.now() - wakingStartTimeRef.current) / 1000))
        );
      } else {
        setElapsedSeconds((s) => s + 1);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [isWaking]);

  // Initial check and polling loop
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      if (cancelled) return;
      await checkHealth();

      if (cancelled) return;

      // If waking, poll quickly; if active, poll occasionally
      const nextDelay = wakingRef.current ? RETRY_INTERVAL_MS : BACKGROUND_POLL_MS;
      timer = setTimeout(run, nextDelay);
    };

    void run();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [checkHealth]);

  const value = useMemo(
    () => ({
      isActive,
      isWaking,
      isChecking,
      elapsedSeconds,
      justWokeUp,
      error,
      checkNow: checkHealth,
    }),
    [isActive, isWaking, isChecking, elapsedSeconds, justWokeUp, error, checkHealth]
  );

  return (
    <ServerStatusContext.Provider value={value}>
      {children}
    </ServerStatusContext.Provider>
  );
}

export function useServerStatus() {
  const ctx = useContext(ServerStatusContext);
  if (!ctx) {
    throw new Error("useServerStatus must be used within ServerStatusProvider");
  }
  return ctx;
}
