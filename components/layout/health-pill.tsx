"use client";

import { RefreshCw } from "lucide-react";
import { useHealth } from "@/lib/hooks/use-health";
import { cn } from "@/lib/utils";

const ONLINE = ["connected", "ok", "healthy"];
const isOnline = (v: string | undefined) => ONLINE.includes(String(v ?? "").toLowerCase());

/** "System health" with every service's status inside one box, always visible (no dropdown). */
export function HealthPill({ className }: { className?: string }) {
  const { health, loading, refreshing, error, refetch } = useHealth();
  const checking = loading && !health;
  // The health check itself failed: the backend can't be reached, so nothing can be shown as online
  const unreachable = Boolean(error);

  const services = [
    { name: "Backend", value: health?.backend },
    ...(health?.groq ? [{ name: "Groq", value: health.groq }] : []),
    { name: "Google AI", value: health?.gemini },
    { name: "Postgres", value: health?.postgres },
    { name: "Qdrant", value: health?.qdrant },
  ];
  const isUp = (v: string | undefined) => !unreachable && isOnline(v);
  const issues = services.filter((s) => !isUp(s.value)).length;

  return (
    <div
      className={cn(
        "inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border bg-card px-3 py-1.5 text-[11px] shadow-sm",
        !checking && issues > 0 && "border-amber-500/40",
        className
      )}
      role="status"
      aria-label={
        checking ? "System health: checking" : unreachable ? "System health: server unreachable" : issues ? `System health: ${issues} issue(s)` : "System health: all online"
      }
    >
      <span className="font-semibold text-foreground">System health</span>
      <span className="h-3 w-px bg-border" aria-hidden />
      {services.map((s) => {
        const up = isUp(s.value);
        return (
          <span
            key={s.name}
            title={`${s.name}: ${checking ? "checking" : up ? "online" : "needs attention"}`}
            className={cn(
              "inline-flex items-center gap-1 font-medium",
              !checking && !up ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                checking ? "animate-pulse bg-muted-foreground" : up ? "bg-emerald-500" : "bg-amber-500"
              )}
            />
            {s.name}
          </span>
        );
      })}
      <button
        type="button"
        onClick={() => void refetch()}
        disabled={refreshing}
        className="-mr-1 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground disabled:cursor-wait"
        aria-label="Check services again"
        title={unreachable ? "Server unreachable. Check again" : "Check again"}
      >
        <RefreshCw className={cn("size-3", (refreshing || checking) && "animate-spin")} />
      </button>
    </div>
  );
}
