"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Download, FileCode2, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  deleteGeneration,
  downloadGenerationFile,
  listGenerations,
  type GenerationSummary,
} from "@/lib/api/resume";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useConfirm } from "@/components/ui/confirm-dialog";

export function HistoryPanel({ refreshKey, onOpen }: { refreshKey: number; onOpen: (generationId: string) => void }) {
  const { confirm, dialog } = useConfirm();
  const [items, setItems] = useState<GenerationSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setItems(await listGenerations());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    listGenerations()
      .then((data) => !cancelled && setItems(data))
      .catch((err) => !cancelled && toast.error(err instanceof Error ? err.message : "Could not load history"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const download = async (g: GenerationSummary, kind: "pdf" | "tex") => {
    try {
      await downloadGenerationFile(g.id, kind, `${g.output_name}.${kind}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    }
  };

  const remove = async (g: GenerationSummary) => {
    const ok = await confirm({
      title: `Delete "${g.output_name}"?`,
      description: "The tailored draft, its downloads and any saved cover letter are removed. Your library is not touched.",
    });
    if (!ok) return;
    try {
      await deleteGeneration(g.id);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>History</CardTitle>
        <CardDescription>Every tailoring run, with its ATS score</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && <Skeleton className="h-16 w-full" />}
        {!loading && items.length === 0 && (
          <p className="text-sm text-muted-foreground">No runs yet. Generate your first tailored resume.</p>
        )}
        {items.map((g) => (
          <div key={g.id} className="flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <div
                className={cn(
                  "flex size-11 shrink-0 items-center justify-center rounded-lg text-sm font-bold tabular-nums",
                  g.ats_score >= g.threshold ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                )}
              >
                {g.ats_score}
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold">{g.output_name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {[g.job_title, g.company].filter(Boolean).join(" at ") || "Job description"}
                  {g.created_at ? ` · ${formatRelativeTime(new Date(g.created_at))}` : ""}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {/* Not released means below the target score, or no PDF (the LaTeX is still there) */}
              {g.ats_score < g.threshold ? (
                <span className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="size-3.5" />
                  Below {g.threshold}
                </span>
              ) : (
                !g.pdf_available && (
                  <span className="flex items-center gap-1 text-xs text-muted-foreground" title="The server couldn't compile a PDF; download the LaTeX and compile it in Overleaf.">
                    <AlertTriangle className="size-3.5" />
                    No PDF
                  </span>
                )
              )}
              <Button size="sm" variant="outline" onClick={() => onOpen(g.id)}>
                <Pencil className="size-3.5" />
                Edit
              </Button>
              {g.pdf_available && (
                <Button size="sm" variant="outline" onClick={() => download(g, "pdf")}>
                  <Download className="size-3.5" />
                  PDF
                </Button>
              )}
              {g.tex_available && (
                <Button size="sm" variant="outline" onClick={() => download(g, "tex")}>
                  <FileCode2 className="size-3.5" />
                  LaTeX
                </Button>
              )}
              <Button
                size="icon"
                variant="ghost"
                className="size-8 text-muted-foreground hover:text-destructive"
                onClick={() => remove(g)}
                aria-label={`Delete ${g.output_name}`}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
      {dialog}
    </Card>
  );
}
