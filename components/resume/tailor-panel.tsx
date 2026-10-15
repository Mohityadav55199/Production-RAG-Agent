"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Briefcase,
  Check,
  CheckCircle2,
  Copy,
  Download,
  FileCode2,
  Loader2,
  Pencil,
  Sparkles,
  Square,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import {
  DEFAULT_RENDER_OPTIONS,
  createJob,
  downloadGenerationFile,
  extractText,
  streamTailor,
  type RenderOptions,
  type ResumeSummary,
  type TailorResult,
  type TailorStep,
} from "@/lib/api/resume";
import { LayoutOptions } from "@/components/resume/layout-options";
import { OutreachPanel } from "@/components/resume/outreach-panel";
import { ScoreReport, ScoreRing } from "@/components/resume/score-report";
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
import { cn, copyText } from "@/lib/utils";

interface TailorPanelProps {
  resumes: ResumeSummary[];
  onGoToLibrary: () => void;
  onFinished: () => void;
  onOpenEditor: (generationId: string) => void;
}

// The job description being worked on survives a reload (this browser only)
const FORM_KEY = "resume-tailor-form";

interface SavedForm {
  jd: string;
  outputName: string;
  layout: RenderOptions;
}

function loadForm(): SavedForm | null {
  try {
    const raw = typeof window === "undefined" ? null : localStorage.getItem(FORM_KEY);
    return raw ? (JSON.parse(raw) as SavedForm) : null;
  } catch {
    return null;
  }
}

interface StepRow {
  key: string;
  message: string;
  status: "running" | "done";
  score?: number;
}

export function TailorPanel({ resumes, onGoToLibrary, onFinished, onOpenEditor }: TailorPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [saved] = useState(loadForm);
  const [jd, setJd] = useState(saved?.jd ?? "");
  const [outputName, setOutputName] = useState(saved?.outputName ?? "");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<StepRow[]>([]);
  const [result, setResult] = useState<TailorResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [reading, setReading] = useState(false);
  const [layout, setLayout] = useState<RenderOptions>({ ...DEFAULT_RENDER_OPTIONS, ...saved?.layout });
  const [tracked, setTracked] = useState(false);

  useEffect(() => {
    try {
      if (jd.trim() || outputName.trim()) localStorage.setItem(FORM_KEY, JSON.stringify({ jd, outputName, layout }));
      else localStorage.removeItem(FORM_KEY);
    } catch {
      // storage blocked: the form still works, it just won't survive a reload
    }
  }, [jd, outputName, layout]);

  const handleTrackJob = async () => {
    if (!result) return;
    try {
      await createJob({
        company: result.jd.company || "Company",
        job_title: result.jd.title || "Position",
        status: "saved",
        ats_score: result.score,
        resume_generation_id: result.generation_id,
        resume_version_name: result.output_name,
        jd_text: jd,
      });
      setTracked(true);
      toast.success("Saved to Job Tracker!");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to track job");
    }
  };

  const noLibrary = resumes.length === 0;
  const canRun = !running && !noLibrary && jd.trim().length >= 80;

  const loadJdFile = async (file: File) => {
    setReading(true);
    try {
      const isText = /\.(txt|md)$/i.test(file.name);
      setJd(isText ? await file.text() : await extractText(file));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not read the file");
    } finally {
      setReading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const applyStep = (step: TailorStep) => {
    const key = `${step.step}-${step.attempt ?? 0}`;
    setSteps((prev) => {
      const row: StepRow = { key, message: step.message, status: step.status, score: step.score };
      const i = prev.findIndex((r) => r.key === key);
      if (i === -1) return [...prev, row];
      const next = [...prev];
      next[i] = row;
      return next;
    });
  };

  const run = async () => {
    setRunning(true);
    setSteps([]);
    setResult(null);
    setError(null);
    abortRef.current = new AbortController();
    try {
      await streamTailor(
        { jd_text: jd.trim(), output_name: outputName.trim() || "resume", options: layout },
        (event) => {
          if (event.type === "step") applyStep(event);
          else if (event.type === "result") setResult(event);
          else if (event.type === "error") setError(event.message);
        },
        abortRef.current.signal
      );
      onFinished();
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "Something went wrong");
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  };

  const download = async (kind: "pdf" | "tex") => {
    if (!result) return;
    try {
      await downloadGenerationFile(result.generation_id, kind, `${result.output_name}.${kind}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    }
  };

  const copyTex = async () => {
    if (!result?.tex) return;
    if (!(await copyText(result.tex))) {
      toast.error("Could not copy. Download the .tex file instead.");
      return;
    }
    setCopied(true);
    toast.success("LaTeX copied");
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Tailor a resume to a job</CardTitle>
          <CardDescription>
            Paste or upload the job description. The agents pick the best facts from your library, write the
            resume, and score it. Aim for an ATS score of 82 or more; you can edit the result and download it either way.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {noLibrary && (
            <div className="flex flex-col gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <span>Your resume library is empty. Add at least one resume first.</span>
              <Button size="sm" variant="outline" onClick={onGoToLibrary}>
                Add resumes
              </Button>
            </div>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="jd" className="text-sm font-medium">Job description</label>
              <div>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && loadJdFile(e.target.files[0])}
                />
                <Button type="button" variant="ghost" size="sm" disabled={running || reading} onClick={() => fileRef.current?.click()}>
                  {reading ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
                  Upload JD file
                </Button>
              </div>
            </div>
            <Textarea
              id="jd"
              value={jd}
              onChange={(e) => setJd(e.target.value)}
              placeholder="Paste the full job description here…"
              className="min-h-[200px] text-sm"
              disabled={running}
            />
            <p className="text-xs text-muted-foreground">
              {jd.trim().length < 80 ? "Paste at least a few lines of the job description." : `${jd.trim().length.toLocaleString()} characters`}
            </p>
          </div>

          <LayoutOptions value={layout} onChange={setLayout} disabled={running} />

          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <label htmlFor="outname" className="text-sm font-medium">File name for the PDF and LaTeX</label>
              <div className="flex items-center gap-2">
                <Input
                  id="outname"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  placeholder="e.g. Asha_Verma_Backend_Engineer"
                  disabled={running}
                />
                <span className="shrink-0 text-xs text-muted-foreground">.pdf / .tex</span>
              </div>
            </div>
            {running ? (
              <Button variant="outline" onClick={() => abortRef.current?.abort()}>
                <Square className="size-4" />
                Stop
              </Button>
            ) : (
              <Button onClick={run} disabled={!canRun}>
                <Sparkles className="size-4" />
                Generate resume
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {(running || steps.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent progress</CardTitle>
            <CardDescription>May take a minute or two. Each rewrite is re-scored.</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="space-y-2">
              {steps.map((s) => (
                <li key={s.key} className="flex items-start gap-2.5 text-sm">
                  {s.status === "running" ? (
                    <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-primary" />
                  ) : (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
                  )}
                  <span className={cn(s.status === "running" && "text-foreground", s.status === "done" && "text-muted-foreground")}>
                    {s.message}
                  </span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <Card className={cn(result.released ? "border-emerald-500/40" : "border-amber-500/40")}>
          <CardHeader>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <ScoreRing score={result.score} threshold={result.threshold} />
              <div className="min-w-0 flex-1">
                {result.released ? (
                  <>
                    <CardTitle className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="size-5" />
                      Ready: ATS score {result.score}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      Your tailored resume passed the {result.threshold} target after {result.attempts} attempt
                      {result.attempts === 1 ? "" : "s"}. You can still edit it and re-score.
                    </CardDescription>
                  </>
                ) : (
                  <>
                    <CardTitle className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="size-5" />
                      Score {result.score} is below the {result.threshold} target
                    </CardTitle>
                    <CardDescription className="mt-1">
                      After {result.attempts} attempts this is the best draft the writer could produce using only
                      facts from your library. You can download it as it is, or open the editor to improve it and see
                      exactly which skills are missing.
                    </CardDescription>
                  </>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => onOpenEditor(result.generation_id)}>
                    <Pencil className="size-4" />
                    Edit and improve
                  </Button>
                  {result.pdf_available && (
                    <Button size="sm" variant="outline" onClick={() => download("pdf")}>
                      <Download className="size-4" />
                      {result.output_name}.pdf
                    </Button>
                  )}
                  {result.tex_available && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => download("tex")}>
                        <FileCode2 className="size-4" />
                        {result.output_name}.tex
                      </Button>
                      <Button size="sm" variant="outline" onClick={copyTex}>
                        {copied ? <Check className="size-4 text-emerald-500" /> : <Copy className="size-4" />}
                        Copy LaTeX
                      </Button>
                    </>
                  )}
                  <Button size="sm" variant="outline" onClick={handleTrackJob} disabled={tracked}>
                    <Briefcase className="size-4" />
                    {tracked ? "Tracked in Jobs" : "Save to Tracker"}
                  </Button>
                </div>
                {!result.pdf_available && result.tex_available && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    The server could not compile a PDF. Paste the LaTeX into Overleaf to compile it.
                  </p>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <ScoreReport report={result.report} threshold={result.threshold} />

            {/* Grounded Outreach: Cover Letter & Recruiter Message */}
            <OutreachPanel
              generationId={result.generation_id}
              company={result.jd.company}
              jobTitle={result.jd.title}
            />

            {result.warnings.length > 0 && (
              <details className="rounded-lg border bg-muted/30 text-sm">
                <summary className="cursor-pointer px-3 py-2 font-medium">
                  Honesty checks ({[...new Set(result.warnings)].length}): things the writer tried that your library doesn&apos;t support
                </summary>
                <ul className="list-disc space-y-1 px-8 pb-3 text-muted-foreground">
                  {[...new Set(result.warnings)].map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            )}

            {result.tex && (
              <details className="rounded-lg border">
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium">View LaTeX code</summary>
                <pre className="max-h-96 overflow-auto border-t bg-muted/30 p-3 text-xs leading-relaxed">{result.tex}</pre>
              </details>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
