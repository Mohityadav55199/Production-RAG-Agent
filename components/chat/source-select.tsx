"use client";

import { useCallback, useEffect, useState } from "react";
import { getSources, type KnowledgeSources } from "@/lib/api/sources";
import { useApp } from "@/lib/context/app-context";
import { cn } from "@/lib/utils";

export function useKnowledgeSources() {
  const { refreshKey } = useApp();
  const [sources, setSources] = useState<KnowledgeSources>({ projects: [], documents: [] });
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      setSources(await getSources());
    } catch {
      // Older backends without /projects/sources: keep the "all" option only
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch, refreshKey]);

  return { sources, loading, refetch };
}

interface SourceSelectProps {
  value: string;
  onChange: (value: string) => void;
  sources: KnowledgeSources;
  includeAll?: boolean;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

/** Native select listing projects and documents; values are "all" | "project:<name>" | "document:<id>". */
export function SourceSelect({
  value,
  onChange,
  sources,
  includeAll = false,
  placeholder = "Choose a project or document…",
  disabled,
  className,
}: SourceSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={cn(
        "h-9 min-w-0 rounded-md border border-input bg-background px-3 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50",
        className
      )}
    >
      {includeAll ? (
        <option value="all">All documents &amp; projects</option>
      ) : (
        <option value="" disabled>
          {placeholder}
        </option>
      )}
      {sources.projects.length > 0 && (
        <optgroup label="Code projects">
          {sources.projects.map((p) => (
            <option key={p.name} value={`project:${p.name}`}>
              {p.name} ({p.file_count} files)
            </option>
          ))}
        </optgroup>
      )}
      {sources.documents.length > 0 && (
        <optgroup label="Documents">
          {sources.documents.map((d) => (
            <option key={d.id} value={`document:${d.id}`}>
              {d.filename}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
