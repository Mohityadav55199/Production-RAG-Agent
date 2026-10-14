"use client";

import { useRef, useState } from "react";
import { motion } from "framer-motion";
import { FileArchive, FolderGit2, Github, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { importGithubProject, importZipProject } from "@/lib/api/projects";
import { useApp } from "@/lib/context/app-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Mode = "github" | "zip";

interface ProjectImportCardProps {
  onImportStarted?: () => void;
}

export function ProjectImportCard({ onImportStarted }: ProjectImportCardProps) {
  const { refresh } = useApp();
  const inputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("github");
  const [repoUrl, setRepoUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (task: () => ReturnType<typeof importGithubProject>) => {
    setBusy(true);
    try {
      const result = await task();
      toast.success(result.message, { duration: 8000 });
      setRepoUrl("");
      refresh();
      onImportStarted?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Project import failed");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleGithub = (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoUrl.trim()) return;
    run(() => importGithubProject(repoUrl.trim()));
  };

  const handleZip = (file: File | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      toast.error("Please choose a .zip file of your project folder.");
      return;
    }
    run(() => importZipProject(file));
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.12 }}
    >
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <FolderGit2 className="size-4" />
            </div>
            <div>
              <CardTitle>Import a Code Project</CardTitle>
              <CardDescription>
                Index a GitHub repo or a zipped project, then ask questions about the code in Chat.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="inline-flex rounded-lg border p-1">
            {(
              [
                { id: "github", label: "GitHub URL", icon: Github },
                { id: "zip", label: "Upload .zip", icon: FileArchive },
              ] as const
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setMode(id)}
                disabled={busy}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  mode === id
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="size-3.5" />
                {label}
              </button>
            ))}
          </div>

          {mode === "github" ? (
            <form onSubmit={handleGithub} className="flex flex-col gap-2 sm:flex-row">
              <Input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
                disabled={busy}
                className="flex-1"
              />
              <Button type="submit" disabled={busy || !repoUrl.trim()}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Github className="size-4" />}
                {busy ? "Downloading…" : "Import repo"}
              </Button>
            </form>
          ) : (
            <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
              <input
                ref={inputRef}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={(e) => handleZip(e.target.files?.[0])}
              />
              <Button onClick={() => inputRef.current?.click()} disabled={busy}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <FileArchive className="size-4" />}
                {busy ? "Uploading…" : "Choose .zip file"}
              </Button>
              <span className="text-xs text-muted-foreground">
                Right-click your project folder → Compress to ZIP. Max 50 MB.
              </span>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Public repos only. node_modules, build output and lock files are skipped; up to 200 key files
            are indexed and appear in Recent Documents as they finish.
          </p>
        </CardContent>
      </Card>
    </motion.div>
  );
}
