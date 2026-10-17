"use client";

import { useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  RefreshCw,
  Server,
  X,
} from "lucide-react";
import { useServerStatus } from "@/lib/context/server-status-context";
import { cn } from "@/lib/utils";

export function RenderServerBanner() {
  const {
    isWaking,
    isChecking,
    elapsedSeconds,
    justWokeUp,
    checkNow,
  } = useServerStatus();

  const [dismissed, setDismissed] = useState(false);
  const [minimized, setMinimized] = useState(false);

  // If just woke up, show positive confirmation
  if (justWokeUp) {
    return (
      <aside
        aria-label="Server status alert"
        className="sticky top-0 z-50 w-full border-b border-emerald-500/30 bg-emerald-500/15 px-4 py-2.5 backdrop-blur-md text-emerald-950 dark:text-emerald-100 shadow-sm transition-all duration-300"
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 text-sm">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <span className="font-semibold">Backend Server Active:</span>
            <span className="text-emerald-800 dark:text-emerald-200">
              Render container is awake and responding. All features are ready to use!
            </span>
          </div>
          <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 font-medium">
            200 OK
          </span>
        </div>
      </aside>
    );
  }

  // If not waking, or user completely dismissed it, don't show
  if (!isWaking || dismissed) {
    return null;
  }

  // If user minimized the banner, show a compact pill so it doesn't take much vertical space
  if (minimized) {
    return (
      <aside
        aria-label="Server status alert"
        className="sticky top-0 z-50 w-full border-b border-amber-500/30 bg-amber-500/15 px-4 py-1.5 backdrop-blur-md text-amber-950 dark:text-amber-100 shadow-sm"
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2">
            <Loader2 className="size-3.5 animate-spin text-amber-600 dark:text-amber-400" />
            <span className="font-semibold">Render Free Tier:</span>
            <span>
              Server waking up ({elapsedSeconds > 0 ? `${elapsedSeconds}s` : "initiating"}… takes ~50s)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void checkNow()}
              disabled={isChecking}
              className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium hover:bg-amber-500/20 transition-colors"
              title="Ping server"
            >
              <RefreshCw className={cn("size-3", isChecking && "animate-spin")} />
              Retry
            </button>
            <button
              onClick={() => setMinimized(false)}
              className="rounded p-0.5 hover:bg-amber-500/20"
              aria-label="Expand banner"
              title="Expand notice"
            >
              <ChevronDown className="size-3.5" />
            </button>
          </div>
        </div>
      </aside>
    );
  }

  // Full detailed banner
  return (
    <aside
      aria-label="Server status alert"
      className="sticky top-0 z-50 w-full border-b border-amber-500/30 bg-gradient-to-r from-amber-500/15 via-orange-500/15 to-amber-500/15 px-4 py-3 backdrop-blur-md text-amber-950 dark:text-amber-100 shadow-md transition-all duration-300"
    >
      <div className="mx-auto max-w-7xl">
        <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
          {/* Main message */}
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 text-amber-600 dark:text-amber-400 border border-amber-500/30">
              <Server className="size-4 animate-pulse" />
            </div>

            <div className="space-y-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/25 px-2.5 py-0.5 text-[11px] font-bold tracking-wide uppercase text-amber-800 dark:text-amber-300 border border-amber-500/30">
                  <span className="size-1.5 rounded-full bg-amber-500 animate-ping" />
                  Render Free Tier Cold Start
                </span>

                <span className="text-xs font-mono font-medium text-amber-800 dark:text-amber-300">
                  {elapsedSeconds > 0 ? `(~${elapsedSeconds}s elapsed)` : "Connecting…"}
                </span>
              </div>

              <p className="text-sm font-semibold tracking-tight text-amber-950 dark:text-amber-100">
                Backend server is currently waking up from sleep.
              </p>

              <p className="text-xs text-amber-800/90 dark:text-amber-200/80 max-w-3xl leading-relaxed">
                Render spins down free services after 15 minutes of inactivity. The container is booting up now (this initial cold start takes <strong>40–60 seconds</strong>).
                Logging in, signing up, or viewing data will complete automatically once ready. Subsequent requests will be fast!
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
            <button
              onClick={() => void checkNow()}
              disabled={isChecking}
              className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-medium hover:bg-amber-500/25 active:scale-95 transition-all disabled:opacity-50"
              title="Ping backend server now"
            >
              <RefreshCw className={cn("size-3.5 text-amber-700 dark:text-amber-300", isChecking && "animate-spin")} />
              <span>{isChecking ? "Pinging…" : "Check Status"}</span>
            </button>

            <button
              onClick={() => setMinimized(true)}
              className="rounded-lg p-1.5 text-amber-700 dark:text-amber-300 hover:bg-amber-500/20 transition-colors"
              aria-label="Minimize banner"
              title="Minimize banner"
            >
              <ChevronUp className="size-4" />
            </button>

            <button
              onClick={() => setDismissed(true)}
              className="rounded-lg p-1.5 text-amber-700 dark:text-amber-300 hover:bg-amber-500/20 transition-colors"
              aria-label="Dismiss banner"
              title="Dismiss for this session"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* Animated activity bar */}
        <div className="mt-2.5 h-1 w-full overflow-hidden rounded-full bg-amber-500/20">
          <div className="h-full w-1/3 rounded-full bg-gradient-to-r from-amber-500 to-orange-500 animate-indeterminate" />
        </div>
      </div>
    </aside>
  );
}
