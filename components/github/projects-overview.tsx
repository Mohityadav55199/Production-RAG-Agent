"use client";

import { AlertCircle, CheckCircle2, FolderGit2, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteDocument } from "@/lib/api/documents";
import { useApp } from "@/lib/context/app-context";
import type { Document } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";

interface ProjectSummary {
  name: string;
  docs: Document[];
  indexed: number;
  processing: number;
  failed: number;
}

function groupByProject(documents: Document[]): ProjectSummary[] {
  const map = new Map<string, ProjectSummary>();
  for (const doc of documents) {
    const name = doc.name.split("/")[0];
    const entry = map.get(name) ?? { name, docs: [], indexed: 0, processing: 0, failed: 0 };
    entry.docs.push(doc);
    if (doc.status === "failed") entry.failed++;
    else if (doc.status === "processing") entry.processing++;
    else entry.indexed++;
    map.set(name, entry);
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
}

interface ProjectsOverviewProps {
  documents: Document[];
  loading: boolean;
  error: string | null;
  onChanged: () => void;
}

export function ProjectsOverview({ documents, loading, error, onChanged }: ProjectsOverviewProps) {
  const { refresh } = useApp();
  const projects = groupByProject(documents);

  const removeProject = async (project: ProjectSummary) => {
    if (!window.confirm(`Delete project "${project.name}" and all ${project.docs.length} indexed files?`)) return;
    const results = await Promise.allSettled(project.docs.map((d) => deleteDocument(d.id)));
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) toast.error(`${failed} files could not be deleted. Try again.`);
    else toast.success(`Deleted "${project.name}"`);
    refresh();
    onChanged();
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FolderGit2 className="size-4" />
          </div>
          <div>
            <CardTitle>Your projects</CardTitle>
            <CardDescription>Each imported repo or zip, with indexing progress</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && <Skeleton className="h-16 w-full" />}
        {error && (
          <p className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle className="size-4" />
            {error}
          </p>
        )}
        {!loading && !error && projects.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No projects yet. Import a GitHub repo or upload a .zip.
          </p>
        )}
        {projects.map((p) => {
          const total = p.docs.length;
          const percent = Math.round(((p.indexed + p.failed) / total) * 100);
          const busy = p.processing > 0;
          return (
            <div key={p.name} className="rounded-xl border p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{p.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                    <span>{total} files</span>
                    {busy ? (
                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                        <Loader2 className="size-3 animate-spin" />
                        Indexing… {p.indexed}/{total}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="size-3" />
                        {p.indexed} indexed
                      </span>
                    )}
                    {p.failed > 0 && (
                      <span className="text-destructive" title={p.docs.find((d) => d.status === "failed")?.error}>
                        {p.failed} failed
                      </span>
                    )}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => removeProject(p)}
                  aria-label={`Delete ${p.name}`}
                  title="Delete project"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              {busy && <Progress value={percent} className="mt-3 h-1.5" />}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
