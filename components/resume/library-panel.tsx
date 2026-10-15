"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, FileCode2, FileText, Loader2, Plus, Trash2, TriangleAlert, Upload } from "lucide-react";
import { toast } from "sonner";
import { addResume, deleteResume, importLayout, listResumes, type ResumeSummary } from "@/lib/api/resume";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useConfirm } from "@/components/ui/confirm-dialog";

export function useResumeLibrary() {
  const [resumes, setResumes] = useState<ResumeSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      setResumes(await listResumes());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load your resumes");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    listResumes()
      .then((data) => !cancelled && setResumes(data))
      .catch((err) => !cancelled && toast.error(err instanceof Error ? err.message : "Could not load your resumes"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // Indexing runs in the background; keep refreshing until every resume is ready, but give up after
  // a few minutes so a stuck job can't keep the page polling forever (the server re-indexes on restart).
  const pendingSince = useRef<number | null>(null);
  useEffect(() => {
    const pending = resumes.some((r) => r.index_status === "pending");
    if (!pending) {
      pendingSince.current = null;
      return;
    }
    pendingSince.current ??= Date.now();
    const id = setInterval(() => {
      if (Date.now() - (pendingSince.current ?? Date.now()) < 5 * 60 * 1000) refetch();
    }, 4000);
    return () => clearInterval(id);
  }, [resumes, refetch]);

  return { resumes, loading, refetch };
}

interface LibraryPanelProps {
  resumes: ResumeSummary[];
  loading: boolean;
  onChanged: () => void;
}

export function LibraryPanel({ resumes, loading, onChanged }: LibraryPanelProps) {
  const { confirm, dialog } = useConfirm();
  const inputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<"file" | "text" | "latex">("file");
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [saveAsTemplate, setSaveAsTemplate] = useState(true);
  const [busy, setBusy] = useState(false);

  const submit = async (input: { file?: File; text?: string; isLatex?: boolean }) => {
    setBusy(true);
    try {
      const added = await addResume({ ...input, label: label.trim() || (input.isLatex ? "LaTeX base resume" : undefined) });
      let extraMsg = "";
      if (input.isLatex && saveAsTemplate && input.text) {
        try {
          await importLayout(null, label.trim() || "LaTeX Template", input.text);
          extraMsg = " & layout template saved";
        } catch {
          // non-fatal: the resume was still indexed into the library
        }
      }
      toast.success(`Added "${added.label}"${extraMsg}. Indexing it for search…`);
      setLabel("");
      setText("");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not add the resume");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const remove = async (resume: ResumeSummary) => {
    const ok = await confirm({
      title: `Remove "${resume.label}" from your library?`,
      description: "Tailoring will no longer use its facts. Past runs keep the drafts they already made.",
      confirmLabel: "Remove",
    });
    if (!ok) return;
    try {
      await deleteResume(resume.id);
      toast.success("Resume removed");
      onChanged();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Add a base resume</CardTitle>
          <CardDescription>
            Add your base resumes (PDF, DOCX, or raw LaTeX). The agent extracts your real facts and only writes what you support.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-3 rounded-lg border p-0.5">
            {(
              [
                { id: "file", label: "Upload file", icon: Upload },
                { id: "text", label: "Paste text", icon: FileText },
                { id: "latex", label: "Paste LaTeX", icon: FileCode2 },
              ] as const
            ).map(({ id, label: l, icon: Icon }) => (
              <button
                key={id}
                type="button"
                disabled={busy}
                onClick={() => setMode(id)}
                className={cn(
                  "flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
                  mode === id ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="size-3.5" />
                {l}
              </button>
            ))}
          </div>

          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={
              mode === "latex"
                ? "Label (optional), e.g. Overleaf LaTeX Resume"
                : "Label (optional), e.g. Backend resume 2026"
            }
            disabled={busy}
          />

          {mode === "file" ? (
            <>
              <input
                ref={inputRef}
                type="file"
                accept=".pdf,.docx,.txt,.md,.tex"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && submit({ file: e.target.files[0] })}
              />
              <Button className="w-full" disabled={busy} onClick={() => inputRef.current?.click()}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
                {busy ? "Reading your resume…" : "Choose PDF, DOCX, TXT or LaTeX"}
              </Button>
            </>
          ) : mode === "latex" ? (
            <>
              <div className="space-y-1.5">
                <Textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={`\\documentclass[letterpaper,11pt]{article}\n\\usepackage{latexsym}\n\\begin{document}\n% Paste your full LaTeX resume here...\n\\section{Experience}\n\\end{document}`}
                  className="min-h-[220px] max-h-[380px] resize-y overflow-y-auto font-mono text-xs leading-relaxed"
                  disabled={busy}
                />
                <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>
                    {text.includes("\\documentclass") || text.includes("\\begin{document}") || text.includes("\\section") ? (
                      <span className="inline-flex items-center gap-1 font-medium text-emerald-600 dark:text-emerald-400">
                        <CheckCircle2 className="size-3" /> LaTeX syntax recognized
                      </span>
                    ) : (
                      "Paste \\documentclass or standard LaTeX code"
                    )}
                  </span>
                  {text.trim().length > 0 && <span>{text.trim().length.toLocaleString()} chars</span>}
                </div>
              </div>

              <label className="flex cursor-pointer items-start gap-2 rounded-lg border bg-muted/30 p-2.5 text-xs">
                <input
                  type="checkbox"
                  checked={saveAsTemplate}
                  onChange={(e) => setSaveAsTemplate(e.target.checked)}
                  disabled={busy}
                  className="mt-0.5 rounded border-muted-foreground"
                />
                <span className="text-muted-foreground">
                  Also save as a <strong>LaTeX layout template</strong> (uses your styling for new resumes).
                </span>
              </label>

              <Button
                className="w-full"
                disabled={busy || text.trim().length < 80}
                onClick={() => submit({ text, isLatex: true })}
              >
                {busy ? <Loader2 className="size-4 animate-spin" /> : <FileCode2 className="size-4" />}
                {busy ? "Parsing LaTeX resume…" : "Add base LaTeX resume"}
              </Button>
            </>
          ) : (
            <>
              <Textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Paste your plain resume text here…"
                className="min-h-[180px] text-sm"
                disabled={busy}
              />
              <Button className="w-full" disabled={busy || text.trim().length < 80} onClick={() => submit({ text })}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
                {busy ? "Analysing…" : "Add pasted resume"}
              </Button>
            </>
          )}
          <p className="text-xs text-muted-foreground">Max 5 MB. Analysing a resume takes a few seconds.</p>
        </CardContent>
      </Card>

      <Card className="lg:col-span-3">
        <CardHeader>
          <CardTitle>Your library</CardTitle>
          <CardDescription>
            {resumes.length} base resume{resumes.length === 1 ? "" : "s"} available to the agent
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading && <Skeleton className="h-20 w-full" />}
          {!loading && resumes.length === 0 && (
            <p className="text-sm text-muted-foreground">No resumes yet. Add your first one on the left.</p>
          )}
          {resumes.map((r) => (
            <div key={r.id} className="flex items-start justify-between gap-3 rounded-xl border p-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-semibold">{r.label}</p>
                  {r.file_type === "tex" && (
                    <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-wider text-primary">
                      LaTeX
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {r.name || "Name not found"} · {r.counts.experience} roles · {r.counts.projects} projects ·{" "}
                  {r.counts.skills} skills
                </p>
                <p className="mt-1.5 flex items-center gap-1.5 text-xs">
                  {r.index_status === "ready" && r.item_count > 0 && (
                    <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="size-3" />
                      Searchable ({r.item_count} items)
                    </span>
                  )}
                  {r.index_status === "ready" && r.item_count === 0 && (
                    <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                      <TriangleAlert className="size-3" />
                      Nothing searchable was found in this resume. Try uploading it again.
                    </span>
                  )}
                  {r.index_status === "pending" && (
                    <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400">
                      <Loader2 className="size-3 animate-spin" />
                      Indexing for search…
                    </span>
                  )}
                  {r.index_status === "failed" && (
                    <span
                      className="flex items-center gap-1 text-amber-600 dark:text-amber-400"
                      title="Semantic search is unavailable for this resume; keyword ranking is used instead."
                    >
                      <TriangleAlert className="size-3" />
                      Indexing failed (keyword fallback)
                    </span>
                  )}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
                onClick={() => remove(r)}
                aria-label={`Remove ${r.label}`}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
      {dialog}
    </div>
  );
}
