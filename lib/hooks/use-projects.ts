"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listProjects, type ProjectProgress } from "@/lib/api/projects";
import { useApp } from "@/lib/context/app-context";

const POLL_MS = 4000;
const WATCH_MS = 15 * 60 * 1000;

/**
 * Projects with their indexing progress. Polls while any file is still processing, and for a
 * while after an import starts (files appear one by one, so "nothing processing" can be momentary).
 */
export function useProjects() {
  const { refreshKey } = useApp();
  const [projects, setProjects] = useState<ProjectProgress[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const watchUntil = useRef(0);

  const refetch = useCallback(async () => {
    try {
      setProjects(await listProjects());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load projects");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch, refreshKey]);

  const busy = projects.some((p) => p.processing > 0);
  useEffect(() => {
    const id = setInterval(() => {
      if (busy || Date.now() < watchUntil.current) refetch();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [busy, refetch]);

  const watch = useCallback(() => {
    watchUntil.current = Date.now() + WATCH_MS;
    refetch();
  }, [refetch]);

  return { projects, loading, error, refetch, watch };
}
