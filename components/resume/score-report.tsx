"use client";

import { AlertTriangle, CheckCircle2, Lightbulb } from "lucide-react";
import type { AtsReport } from "@/lib/api/resume";
import { cn } from "@/lib/utils";

interface ScoreRingProps {
  score: number;
  threshold?: number;
  size?: number;
}

export function ScoreRing({ score, threshold, size = 120 }: ScoreRingProps) {
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  const passed = threshold !== undefined ? score >= threshold : score >= 80;
  const color = passed ? "text-emerald-500" : score >= 60 ? "text-amber-500" : "text-rose-500";

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 120 120" className="size-full -rotate-90" aria-hidden>
        <circle cx="60" cy="60" r={radius} fill="none" strokeWidth="10" className="stroke-muted" />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - Math.min(100, score) / 100)}
          className={cn("stroke-current transition-all duration-700", color)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-3xl font-bold tabular-nums", color)}>{score}</span>
        <span className="text-[11px] text-muted-foreground">
          {threshold !== undefined ? `need ${threshold}` : "out of 100"}
        </span>
      </div>
    </div>
  );
}

function Chip({ children, tone }: { children: React.ReactNode; tone: "good" | "bad" | "warn" }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs font-medium",
        tone === "good" && "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
        tone === "bad" && "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-400",
        tone === "warn" && "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400"
      )}
    >
      {children}
    </span>
  );
}

interface ScoreReportProps {
  report: AtsReport;
  threshold?: number;
  className?: string;
}

export function ScoreReport({ report, threshold, className }: ScoreReportProps) {
  return (
    <div className={cn("space-y-5", className)}>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <ScoreRing score={report.total} threshold={threshold} />
        <div className="min-w-0 flex-1 space-y-2.5">
          {report.components.map((c) => (
            <div key={c.key}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="font-medium">
                  {c.label} <span className="text-xs font-normal text-muted-foreground">({c.weight}%)</span>
                </span>
                <span className="tabular-nums text-muted-foreground">{c.score}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-700",
                    c.score >= 80 ? "bg-emerald-500" : c.score >= 60 ? "bg-amber-500" : "bg-rose-500"
                  )}
                  style={{ width: `${c.score}%` }}
                />
              </div>
              {c.details && <p className="mt-0.5 text-xs text-muted-foreground">{c.details}</p>}
            </div>
          ))}
        </div>
      </div>

      {!report.pdf_checked && (
        <p className="text-xs text-muted-foreground">
          Scored from the resume text. A compiled PDF was not available, so layout checks were skipped.
        </p>
      )}

      {report.has_jd && (
        <div className="space-y-3">
          {report.missing_must.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <AlertTriangle className="size-4 text-rose-500" />
                Missing required skills
              </p>
              <div className="flex flex-wrap gap-1.5">
                {report.missing_must.map((t) => (
                  <Chip key={t} tone="bad">{t}</Chip>
                ))}
              </div>
            </div>
          )}
          {report.missing_nice.length > 0 && (
            <div>
              <p className="mb-1.5 text-sm font-medium">Missing preferred skills</p>
              <div className="flex flex-wrap gap-1.5">
                {report.missing_nice.map((t) => (
                  <Chip key={t} tone="warn">{t}</Chip>
                ))}
              </div>
            </div>
          )}
          {report.matched.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <CheckCircle2 className="size-4 text-emerald-500" />
                Matched
              </p>
              <div className="flex flex-wrap gap-1.5">
                {report.matched.map((t) => (
                  <Chip key={t} tone="good">{t}</Chip>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {report.fixes.length > 0 && (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
            <Lightbulb className="size-4 text-amber-500" />
            How to improve
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {report.fixes.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
