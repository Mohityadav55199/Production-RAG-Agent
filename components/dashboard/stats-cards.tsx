"use client";

import { AlertCircle, FileText, HardDrive, Layers } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { DashboardStats } from "@/lib/types";
import { cn, formatBytes } from "@/lib/utils";

interface StatsCardsProps {
  stats: DashboardStats;
  loading?: boolean;
  error?: string | null;
  /** One small line instead of three tiles (used beside the chat). */
  compact?: boolean;
}

/** Slim one-row summary: documents, chunks and storage. */
export function StatsCards({ stats, loading, error, compact = false }: StatsCardsProps) {
  const limited = stats.storageLimit > 0;
  const storagePercent = limited
    ? Math.min(100, Math.round((stats.storageUsed / stats.storageLimit) * 100))
    : 0;
  const storageLeft = Math.max(0, stats.storageLimit - stats.storageUsed);
  const nearlyFull = limited && storagePercent >= 90;
  // "412 MB left of 500 MB" (or just what's used when there's no limit)
  const storageText = limited
    ? `${formatBytes(storageLeft)} left of ${formatBytes(stats.storageLimit)}`
    : `${formatBytes(stats.storageUsed)} used`;
  const storageTitle = limited
    ? `${formatBytes(stats.storageUsed)} used, ${formatBytes(storageLeft)} left of ${formatBytes(stats.storageLimit)} (${storagePercent}%)`
    : `${formatBytes(stats.storageUsed)} used, no limit`;

  if (error) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
        <AlertCircle className="size-4 shrink-0" />
        <span>{error}</span>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="space-y-1.5 rounded-xl border bg-card px-4 py-2 text-sm">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {loading ? (
            <Skeleton className="h-5 w-48" />
          ) : (
            <>
              <span className="flex items-center gap-1.5">
                <FileText className="size-3.5 text-blue-600 dark:text-blue-400" />
                <strong className="font-semibold">{stats.totalDocuments.toLocaleString()}</strong>
                <span className="text-muted-foreground">documents</span>
              </span>
              <span className="flex items-center gap-1.5">
                <Layers className="size-3.5 text-violet-600 dark:text-violet-400" />
                <strong className="font-semibold">{stats.totalChunks.toLocaleString()}</strong>
                <span className="text-muted-foreground">chunks</span>
              </span>
              <span className="flex items-center gap-1.5" title={storageTitle}>
                <HardDrive className="size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                <span className={cn("whitespace-nowrap", nearlyFull ? "font-medium text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
                  {storageText}
                </span>
              </span>
            </>
          )}
        </div>
        {!loading && limited && (
          <Progress value={storagePercent} className="h-1" aria-label={`Storage ${storagePercent}% used`} />
        )}
      </div>
    );
  }

  const tiles = [
    {
      key: "documents",
      label: "Documents",
      value: stats.totalDocuments.toLocaleString(),
      icon: FileText,
      tint: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
    },
    {
      key: "chunks",
      label: "Chunks",
      value: stats.totalChunks.toLocaleString(),
      icon: Layers,
      tint: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {tiles.map((tile) => (
        <div
          key={tile.key}
          className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3"
        >
          <div className={`flex size-9 shrink-0 items-center justify-center rounded-lg ${tile.tint}`}>
            <tile.icon className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{tile.label}</p>
            {loading ? (
              <Skeleton className="mt-1 h-6 w-12" />
            ) : (
              <p className="text-xl font-bold leading-tight tracking-tight">{tile.value}</p>
            )}
          </div>
        </div>
      ))}

      <div className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
          <HardDrive className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-xs text-muted-foreground">Storage</p>
            {!loading && limited && (
              <p className="truncate text-xs text-muted-foreground">{storagePercent}% used</p>
            )}
          </div>
          {loading ? (
            <Skeleton className="mt-1 h-6 w-16" />
          ) : (
            <>
              <p
                className={cn("text-base font-bold leading-tight tracking-tight", nearlyFull && "text-amber-700 dark:text-amber-400")}
                title={storageTitle}
              >
                {storageText}
              </p>
              {limited && <Progress value={storagePercent} className="mt-1 h-1.5" />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
