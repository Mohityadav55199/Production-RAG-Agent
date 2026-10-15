"use client";

import { useCallback, useEffect, useState } from "react";
import { getHealth } from "@/lib/api/health";
import type { HealthInfo } from "@/lib/types";

// A check that answers instantly still shows the spinner briefly, so a click visibly did something
const MIN_SPIN_MS = 600;

export function useHealth(pollIntervalMs = 30000) {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [loading, setLoading] = useState(true);       // first check only
  const [refreshing, setRefreshing] = useState(false); // a check asked for with a refresh button
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await getHealth();
      setHealth(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load health");
    } finally {
      setLoading(false);
    }
  }, []);

  /** Check again now (refresh buttons). */
  const refetch = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([load(), new Promise((resolve) => setTimeout(resolve, MIN_SPIN_MS))]);
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  useEffect(() => {
    load();
    if (!pollIntervalMs) return;
    const interval = setInterval(load, pollIntervalMs);
    return () => clearInterval(interval);
  }, [pollIntervalMs, load]);

  return { health, loading, refreshing, error, refetch };
}
