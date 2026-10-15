"use client";

import { AlertCircle, FileText, HardDrive, Layers } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import type { DashboardStats } from "@/lib/types";
import { formatBytes } from "@/lib/utils";

interface StatsCardsProps {
  stats: DashboardStats;
  loading?: boolean;
  error?: string | null;
  /** One small line instead of three tiles (used beside the chat). */
  compact?: boolean;
}

/** Slim one-row summary: documents, chunks and storage. */
export function StatsCards({ stats, loading, error, compact = false }: StatsCardsProps) {
  const storagePercent = stats.storageLimit
    ? Math.min(100, Math.round((stats.storageUsed / stats.storageLimit) * 100))
    : 0;

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
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border bg-card px-4 py-2 text-sm">
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
            <span className="flex min-w-[8rem] flex-1 items-center gap-1.5" title={`${formatBytes(stats.storageUsed)} of ${formatBytes(stats.storageLimit)}`}>
              <HardDrive className="size-3.5 text-emerald-600 dark:text-emerald-400" />
              <span className="text-muted-foreground">{storagePercent}%</span>
              <Progress value={storagePercent} className="h-1.5 flex-1" />
            </span>
          </>
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
            {!loading && (
              <p className="truncate text-xs text-muted-foreground">
                {formatBytes(stats.storageUsed)} of {formatBytes(stats.storageLimit)}
              </p>
            )}
          </div>
          {loading ? (
            <Skeleton className="mt-1 h-6 w-16" />
          ) : (
            <>
              <p className="text-xl font-bold leading-tight tracking-tight">{storagePercent}%</p>
              <Progress value={storagePercent} className="mt-1 h-1.5" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
