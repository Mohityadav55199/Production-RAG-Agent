"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, FolderGit2, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { deleteProject, type ProjectProgress } from "@/lib/api/projects";
import { useApp } from "@/lib/context/app-context";
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

interface ProjectsOverviewProps {
  projects: ProjectProgress[];
  loading: boolean;
  error: string | null;
  onChanged: () => void;
}

export function ProjectsOverview({ projects, loading, error, onChanged }: ProjectsOverviewProps) {
  const { refresh } = useApp();
  const [deleting, setDeleting] = useState<string | null>(null);

  const remove = async (project: ProjectProgress) => {
    if (!window.confirm(`Delete project "${project.name}" and all ${project.total} indexed files?`)) return;
    setDeleting(project.name);
    try {
      await deleteProject(project.name);
      toast.success(`Deleted "${project.name}"`);
      refresh();
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete the project");
    } finally {
      setDeleting(null);
    }
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
          const percent = p.total ? Math.round(((p.indexed + p.failed) / p.total) * 100) : 0;
          const busy = p.processing > 0;
          return (
            <div key={p.name} className="rounded-xl border p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{p.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                    <span>{p.total} files</span>
                    {busy ? (
                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                        <Loader2 className="size-3 animate-spin" />
                        Indexing… {p.indexed}/{p.total}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="size-3" />
                        {p.indexed} indexed
                      </span>
                    )}
                    {p.failed > 0 && (
                      <span className="text-destructive" title={p.first_error ?? undefined}>
                        {p.failed} failed
                      </span>
                    )}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
                  onClick={() => remove(p)}
                  disabled={deleting === p.name}
                  aria-label={`Delete ${p.name}`}
                  title="Delete project"
                >
                  {deleting === p.name ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
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
