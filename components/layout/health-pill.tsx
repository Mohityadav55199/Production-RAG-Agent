"use client";

import { RefreshCw } from "lucide-react";
import { useHealth } from "@/lib/hooks/use-health";
import { cn } from "@/lib/utils";

const ONLINE = ["connected", "ok", "healthy"];
const isOnline = (v: string | undefined) => ONLINE.includes(String(v ?? "").toLowerCase());

/** System health as small inline status chips: one per service, no dropdown. */
export function HealthPill({ className }: { className?: string }) {
  const { health, loading, refetch } = useHealth();
  const checking = loading && !health;

  const services = [
    { name: "Backend", value: health?.backend },
    ...(health?.groq ? [{ name: "Groq", value: health.groq }] : []),
    { name: "Google AI", value: health?.gemini },
    { name: "Postgres", value: health?.postgres },
    { name: "Qdrant", value: health?.qdrant },
  ];

  return (
    <div className={cn("flex flex-wrap items-center justify-end gap-1", className)} aria-label="System health">
      {services.map((s) => {
        const up = isOnline(s.value);
        return (
          <span
            key={s.name}
            title={`${s.name}: ${checking ? "checking" : up ? "online" : "needs attention"}`}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border bg-card px-2 py-0.5 text-[11px] font-medium",
              !checking && !up && "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-400"
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                checking ? "animate-pulse bg-muted-foreground" : up ? "bg-emerald-500" : "bg-amber-500"
              )}
            />
            <span className="hidden sm:inline">{s.name}</span>
            <span className="sr-only sm:hidden">{s.name}</span>
          </span>
        );
      })}
      <button
        type="button"
        onClick={refetch}
        disabled={loading}
        className="rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="Check services again"
        title="Check again"
      >
        <RefreshCw className={cn("size-3", loading && "animate-spin")} />
      </button>
    </div>
  );
}
