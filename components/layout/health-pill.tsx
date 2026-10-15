"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, RefreshCw } from "lucide-react";
import { useHealth } from "@/lib/hooks/use-health";
import { cn } from "@/lib/utils";

const ONLINE = ["connected", "ok", "healthy"];
const isOnline = (v: string | undefined) => ONLINE.includes(String(v ?? "").toLowerCase());

/** System health as a small pill; click it for the per-service breakdown. */
export function HealthPill({ className }: { className?: string }) {
  const { health, loading, refetch } = useHealth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const services = [
    { name: "Backend API", value: health?.backend },
    ...(health?.groq ? [{ name: "Groq LLM", value: health.groq }] : []),
    { name: "Google AI", value: health?.gemini },
    { name: "PostgreSQL", value: health?.postgres },
    { name: "Qdrant", value: health?.qdrant },
  ];
  const offline = services.filter((s) => !isOnline(s.value));
  const state = loading && !health ? "checking" : offline.length === 0 ? "ok" : "issues";
  const label =
    state === "checking" ? "Checking…" : state === "ok" ? "All systems up" : `${offline.length} issue${offline.length > 1 ? "s" : ""}`;

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`System health: ${label}`}
        className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-xs font-medium shadow-sm transition-colors hover:bg-muted"
      >
        <span
          className={cn(
            "size-2 rounded-full",
            state === "ok" ? "bg-emerald-500" : state === "issues" ? "bg-amber-500" : "animate-pulse bg-muted-foreground"
          )}
        />
        <span className="whitespace-nowrap">{label}</span>
        <ChevronDown className={cn("size-3 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-2 w-60 rounded-xl border bg-popover p-3 text-sm text-popover-foreground shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold">System health</span>
            <button
              type="button"
              onClick={refetch}
              disabled={loading}
              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Check again"
            >
              <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
            </button>
          </div>
          <ul className="space-y-1.5">
            {services.map((s) => (
              <li key={s.name} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2">
                  <span className={cn("size-1.5 rounded-full", isOnline(s.value) ? "bg-emerald-500" : "bg-amber-500")} />
                  {s.name}
                </span>
                <span className={cn("text-xs", isOnline(s.value) ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400")}>
                  {isOnline(s.value) ? "Online" : loading && !health ? "Checking" : "Needs attention"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
