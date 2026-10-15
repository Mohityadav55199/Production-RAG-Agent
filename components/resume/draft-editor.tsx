"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  BriefcaseBusiness,
  CheckCircle2,
  Columns2,
  Download,
  FileCode2,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  downloadGenerationFile,
  getGeneration,
  markApplied,
  regenerateBullet,
  rescoreGeneration,
  type BulletInfo,
  type BulletOption,
  type GenerationDetail,
  type RenderOptions,
  type ResumeProfile,
} from "@/lib/api/resume";
import { CompareView } from "@/components/resume/compare-view";
import { LayoutOptions } from "@/components/resume/layout-options";
import { OutreachPanel } from "@/components/resume/outreach-panel";
import { ScoreReport, ScoreRing } from "@/components/resume/score-report";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const MAX_BULLETS = 10;
const MAX_BULLET_CHARS = 600;

// Unsaved edits survive a reload: kept per run in this browser, alongside the server version they started from
const unsavedKey = (generationId: string) => `resume-unsaved:${generationId}`;

interface UnsavedEdits {
  base: string; // JSON of the server draft + options the edits were made on
  draft: ResumeProfile;
  options: RenderOptions;
}

function readUnsaved(generationId: string): UnsavedEdits | null {
  try {
    const raw = localStorage.getItem(unsavedKey(generationId));
    return raw ? (JSON.parse(raw) as UnsavedEdits) : null;
  } catch {
    return null;
  }
}

function writeUnsaved(generationId: string, edits: UnsavedEdits | null) {
  try {
    if (edits) localStorage.setItem(unsavedKey(generationId), JSON.stringify(edits));
    else localStorage.removeItem(unsavedKey(generationId));
  } catch {
    // storage blocked or full: edits still live in memory
  }
}

const serverVersion = (d: GenerationDetail) => JSON.stringify([d.draft, d.options]);

type Kind = "experience" | "project";

function move<T>(items: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

const STATUS_STYLE: Record<string, { label: string; className: string; title: string }> = {
  original: {
    label: "Your wording",
    className: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    title: "Exactly as written in your library",
  },
  reworded: {
    label: "Reworded",
    className: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
    title: "Rewritten from a bullet in your library",
  },
  new: {
    label: "No library source",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
    title: "Nothing in your library matches this text",
  },
  edited: {
    label: "Edited, not scored",
    className: "bg-muted text-muted-foreground",
    title: "You changed this since the last score",
  },
};

// ── One bullet ───────────────────────────────────────────────────────────────

interface BulletRowProps {
  text: string;
  info: BulletInfo | undefined;
  canUp: boolean;
  canDown: boolean;
  onChange: (text: string) => void;
  onRemove: () => void;
  onMove: (delta: number) => void;
  suggest: (note: string) => Promise<BulletOption[]>;
}

function BulletRow({ text, info, canUp, canDown, onChange, onRemove, onMove, suggest }: BulletRowProps) {
  const [showSource, setShowSource] = useState(false);
  const [panel, setPanel] = useState(false);
  const [note, setNote] = useState("");
  const [options, setOptions] = useState<BulletOption[]>([]);
  const [loading, setLoading] = useState(false);

  const status = STATUS_STYLE[info ? info.status : "edited"];

  const getOptions = async () => {
    setLoading(true);
    try {
      setOptions(await suggest(note));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not get suggestions");
    } finally {
      setLoading(false);
    }
  };

  return (
    <li className="rounded-lg border bg-background/60 p-2">
      <div className="flex items-start gap-2">
        <Textarea
          value={text}
          maxLength={MAX_BULLET_CHARS}
          onChange={(e) => onChange(e.target.value)}
          // Grows with its text so a whole bullet is readable on a phone (rows is the fallback where
          // field-sizing isn't supported)
          rows={Math.min(8, Math.max(1, Math.ceil(text.length / 90)))}
          className="min-h-9 flex-1 resize-y py-1.5 text-sm [field-sizing:content]"
          aria-label="Bullet text"
        />
        <div className="flex shrink-0 items-center">
          <Button size="icon" variant="ghost" className="size-7" disabled={!canUp} onClick={() => onMove(-1)} aria-label="Move bullet up">
            <ArrowUp className="size-3.5" />
          </Button>
          <Button size="icon" variant="ghost" className="size-7" disabled={!canDown} onClick={() => onMove(1)} aria-label="Move bullet down">
            <ArrowDown className="size-3.5" />
          </Button>
          <Button size="icon" variant="ghost" className="size-7 text-muted-foreground hover:text-destructive" onClick={onRemove} aria-label="Remove bullet">
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
        <span title={status.title} className={cn("rounded-full px-2 py-0.5 font-medium", status.className)}>
          {status.label}
        </span>
        {info?.source && info.status === "reworded" && (
          <button type="button" className="text-muted-foreground underline-offset-2 hover:underline" onClick={() => setShowSource((v) => !v)}>
            {showSource ? "Hide" : "Show"} your original
          </button>
        )}
        <button
          type="button"
          className="flex items-center gap-1 text-primary underline-offset-2 hover:underline"
          onClick={() => setPanel((v) => !v)}
        >
          <Sparkles className="size-3" />
          Rewrite
        </button>
        {info?.skills && info.skills.length > 0 && (
          <span className="flex flex-wrap items-center gap-1" aria-label="Job skills this bullet covers">
            <span className="text-muted-foreground">Covers</span>
            {info.skills.map((s) => (
              <span
                key={s.term}
                title={s.required ? "Required by the job" : "Preferred by the job"}
                className={cn(
                  "rounded-full border px-1.5 py-px font-medium",
                  s.required
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                    : "border-border bg-muted/50 text-muted-foreground"
                )}
              >
                {s.term}
              </span>
            ))}
          </span>
        )}
      </div>

      {showSource && info?.source && (
        <p className="mt-1.5 rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
          <span className="font-medium">Your library: </span>
          {info.source}
        </p>
      )}

      {panel && (
        <div className="mt-2 space-y-2 rounded-md border border-dashed p-2.5">
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={note}
              maxLength={200}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional note, e.g. shorter, lead with the API work"
              className="h-8 text-xs"
            />
            <Button size="sm" variant="outline" disabled={loading} onClick={getOptions}>
              {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
              {options.length ? "Try again" : "Get 3 options"}
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">Options only use facts from your library.</p>
          {options.map((o, i) => (
            <div key={i} className="flex items-start gap-2 rounded-md bg-muted/40 p-2 text-sm">
              <span className="flex-1">{o.text}</span>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  onChange(o.text);
                  setPanel(false);
                  setOptions([]);
                }}
              >
                Use
              </Button>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

// ── Bullets of one role or project ───────────────────────────────────────────

interface ItemBulletsProps {
  generationId: string;
  kind: Kind;
  name: string;
  bullets: string[];
  infoFor: (text: string) => BulletInfo | undefined;
  unused: string[];
  onChange: (bullets: string[]) => void;
}

function ItemBullets({ generationId, kind, name, bullets, infoFor, unused, onChange }: ItemBulletsProps) {
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);

  const suggestFor = (current: string) => (note: string) =>
    regenerateBullet(generationId, {
      kind,
      name,
      current,
      already_used: bullets.filter((b) => b !== current),
      instruction: note,
    });

  const writeNew = async () => {
    setBusy(true);
    try {
      const options = await suggestFor("")("");
      if (options[0]) {
        onChange([...bullets, options[0].text]);
        setAdding(false);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not write a bullet");
    } finally {
      setBusy(false);
    }
  };

  const full = bullets.length >= MAX_BULLETS;
  return (
    <div className="mt-2 space-y-2">
      <ul className="space-y-2">
        {bullets.map((b, i) => (
          <BulletRow
            key={i}
            text={b}
            info={infoFor(b)}
            canUp={i > 0}
            canDown={i < bullets.length - 1}
            onChange={(text) => onChange(bullets.map((x, j) => (j === i ? text : x)))}
            onRemove={() => onChange(bullets.filter((_, j) => j !== i))}
            onMove={(delta) => onChange(move(bullets, i, delta))}
            suggest={suggestFor(b)}
          />
        ))}
      </ul>

      {!full && (
        <div>
          <Button size="sm" variant="ghost" onClick={() => setAdding((v) => !v)}>
            <Plus className="size-3.5" />
            Add a bullet
          </Button>
          {adding && (
            <div className="mt-1 space-y-1.5 rounded-md border p-2.5">
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={busy} onClick={writeNew}>
                  {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
                  Write one for this job
                </Button>
                <Button size="sm" variant="outline" onClick={() => { onChange([...bullets, ""]); setAdding(false); }}>
                  Blank bullet
                </Button>
              </div>
              {unused.length > 0 && (
                <>
                  <p className="pt-1 text-xs font-medium text-muted-foreground">Left out of this draft, from your library</p>
                  {unused.filter((u) => !bullets.includes(u)).map((u) => (
                    <div key={u} className="flex items-start gap-2 rounded-md bg-muted/40 p-2 text-sm">
                      <span className="flex-1">{u}</span>
                      <Button size="sm" variant="secondary" onClick={() => { onChange([...bullets, u]); setAdding(false); }}>
                        Add
                      </Button>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── The editor ───────────────────────────────────────────────────────────────

interface DraftEditorProps {
  generationId: string;
  onChanged?: () => void;
  /** Scroll to the cover letter / recruiter message section once loaded. */
  focusOutreach?: boolean;
}

export function DraftEditor({ generationId, onChanged, focusOutreach }: DraftEditorProps) {
  const [detail, setDetail] = useState<GenerationDetail | null>(null);
  const [draft, setDraft] = useState<ResumeProfile | null>(null);
  const [options, setOptions] = useState<RenderOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scoring, setScoring] = useState(false);
  const [applying, setApplying] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [version, setVersion] = useState(0); // bumps on every server update, so the outreach panel reloads
  const outreachRef = useRef<HTMLDivElement>(null);

  const apply = useCallback((d: GenerationDetail, restore = false) => {
    setDetail(d);
    setVersion((v) => v + 1);
    const unsaved = restore ? readUnsaved(generationId) : null;
    if (unsaved && unsaved.base === serverVersion(d) && d.editable) {
      setDraft(unsaved.draft);
      setOptions(unsaved.options);
      toast.info("Restored your unsaved edits. Re-score to apply them.");
    } else {
      writeUnsaved(generationId, null);
      setDraft(d.draft);
      setOptions(d.options);
    }
  }, [generationId]);

  useEffect(() => {
    let cancelled = false;
    getGeneration(generationId)
      .then((d) => !cancelled && apply(d, true))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load this resume"));
    return () => {
      cancelled = true;
    };
  }, [generationId, apply]);

  const dirty = useMemo(
    () => !!detail && (JSON.stringify(draft) !== JSON.stringify(detail.draft) || JSON.stringify(options) !== JSON.stringify(detail.options)),
    [detail, draft, options]
  );

  // Keep unsaved edits across reloads, and warn before the page is closed with edits pending
  useEffect(() => {
    if (!detail || !draft || !options) return;
    writeUnsaved(generationId, dirty ? { base: serverVersion(detail), draft, options } : null);
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [generationId, detail, draft, options, dirty]);

  useEffect(() => {
    if (focusOutreach && detail) outreachRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focusOutreach, detail]);

  if (error) {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        {error}
      </div>
    );
  }
  if (!detail || !draft || !options) return <Skeleton className="h-64 w-full" />;

  if (!detail.editable) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>This run can&apos;t be edited</CardTitle>
          <CardDescription>
            It was created before editing existed. Generate it again to get an editable draft.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const annotated = detail.annotated;
  const roleInfo = (company: string) => annotated?.experience.find((r) => r.company === company);
  const projectInfo = (name: string) => annotated?.projects.find((p) => p.name === name);
  const infoIn = (bullets: BulletInfo[] | undefined) => (text: string) => bullets?.find((b) => b.text === text);

  const patch = (change: Partial<ResumeProfile>) => setDraft({ ...draft, ...change });
  const setRole = (i: number, bullets: string[]) =>
    patch({ experience: draft.experience.map((r, j) => (j === i ? { ...r, bullets } : r)) });
  const setProject = (i: number, bullets: string[]) =>
    patch({ projects: draft.projects.map((p, j) => (j === i ? { ...p, bullets } : p)) });

  const rescore = async () => {
    setScoring(true);
    try {
      const d = await rescoreGeneration(generationId, draft, options);
      apply(d);
      onChanged?.();
      toast.success(`Re-scored: ${d.ats_score}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not re-score");
    } finally {
      setScoring(false);
    }
  };

  const markAsApplied = async () => {
    setApplying(true);
    try {
      const job = await markApplied(generationId);
      setDetail({ ...detail, job });
      toast.success(job.status === "applied" ? "Marked as applied in your job tracker" : `Job tracker updated (${job.status})`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update the job tracker");
    } finally {
      setApplying(false);
    }
  };

  const download = async (kind: "pdf" | "tex") => {
    try {
      await downloadGenerationFile(generationId, kind, `${detail.output_name}.${kind}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    }
  };

  const addFromLibrary = (from: { kind: Kind; item: string; bullet: string }) => {
    const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");
    if (from.kind === "experience") {
      const i = draft.experience.findIndex((r) => norm(r.company) === norm(from.item));
      if (i === -1 || draft.experience[i].bullets.includes(from.bullet)) return false;
      setRole(i, [...draft.experience[i].bullets, from.bullet]);
      return true;
    }
    const i = draft.projects.findIndex((p) => norm(p.name) === norm(from.item));
    if (i === -1 || draft.projects[i].bullets.includes(from.bullet)) return false;
    setProject(i, [...draft.projects[i].bullets, from.bullet]);
    return true;
  };

  const gap = detail.gap;
  const aiDraftDiffers = JSON.stringify(draft) !== JSON.stringify(detail.ai_draft);

  return (
    // Desktop: the draft on the left; the score and downloads stay in view on the right.
    // Phone: the score card on top, then the draft.
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] xl:grid-cols-[minmax(0,1fr)_22rem]">
      <aside className="flex flex-col gap-4 lg:sticky lg:top-20 lg:order-2 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto">
        {/* Score and downloads */}
        <Card className={cn("shrink-0", detail.below_threshold ? "border-amber-500/40" : "border-emerald-500/40")}>
          <CardHeader>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center lg:flex-col lg:items-start">
              <ScoreRing score={detail.ats_score} threshold={detail.threshold} />
              <div className="min-w-0 flex-1 space-y-2">
                <CardTitle className="flex items-center gap-2">
                  {detail.below_threshold ? (
                    <span className="flex items-center gap-2 text-amber-600 dark:text-amber-400">
                      <AlertTriangle className="size-5" />
                      Score {detail.ats_score} is below the {detail.threshold} target
                    </span>
                  ) : (
                    <span className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="size-5" />
                      Score {detail.ats_score}: at or above the {detail.threshold} target
                    </span>
                  )}
                </CardTitle>
                <CardDescription>
                  {detail.job_title ? `${detail.job_title}${detail.company ? ` at ${detail.company}` : ""}. ` : ""}
                  {detail.below_threshold
                    ? "You can still download this draft. Improve the score by editing it below, or see what is missing."
                    : "Edit anything below and re-score to keep the file in sync."}
                </CardDescription>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={!detail.pdf_available || dirty} onClick={() => download("pdf")}>
                    <Download className="size-4" />
                    {detail.output_name}.pdf
                  </Button>
                  <Button size="sm" variant="outline" disabled={!detail.tex_available || dirty} onClick={() => download("tex")}>
                    <FileCode2 className="size-4" />
                    .tex
                  </Button>
                  <Button size="sm" variant={dirty ? "default" : "outline"} disabled={scoring || !dirty} onClick={rescore}>
                    {scoring ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                    Re-score
                  </Button>
                  {detail.job && detail.job.status !== "saved" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 text-xs font-medium capitalize text-emerald-700 dark:text-emerald-400">
                      <BriefcaseBusiness className="size-3.5" />
                      {detail.job.status}
                      {detail.job.applied_date ? ` · ${new Date(detail.job.applied_date).toLocaleDateString()}` : ""}
                    </span>
                  ) : (
                    <Button size="sm" variant="outline" disabled={applying} onClick={markAsApplied}>
                      {applying ? <Loader2 className="size-4 animate-spin" /> : <BriefcaseBusiness className="size-4" />}
                      Mark as applied
                    </Button>
                  )}
                  {detail.library && (
                    <Button size="sm" variant={comparing ? "secondary" : "ghost"} onClick={() => setComparing((v) => !v)} aria-expanded={comparing}>
                      <Columns2 className="size-4" />
                      {comparing ? "Hide comparison" : "Compare with your original"}
                    </Button>
                  )}
                  {aiDraftDiffers && (
                    <Button size="sm" variant="ghost" onClick={() => { setDraft(detail.ai_draft); }}>
                      <RotateCcw className="size-4" />
                      Reset to AI draft
                    </Button>
                  )}
                </div>
                {dirty && (
                  <p className="text-xs text-muted-foreground">
                    You have unsaved changes. Re-score to apply them; downloads reflect the last scored version.
                  </p>
                )}
                {!detail.pdf_available && (
                  <p className="text-xs text-muted-foreground">
                    The server could not compile a PDF. Download the .tex and compile it in Overleaf.
                  </p>
                )}
              </div>
            </div>
          </CardHeader>
        </Card>
      </aside>

      <div className="min-w-0 space-y-6 lg:order-1">
        {/* Your library next to the tailored draft */}
        {comparing && detail.library && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Your original next to the tailored draft</CardTitle>
              <CardDescription>
                Left: your resume as it is in your library. Right: this draft, including edits you haven&apos;t re-scored yet.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CompareView library={detail.library} draft={draft} annotated={annotated} />
            </CardContent>
          </Card>
        )}

        {/* Gap report */}
        {gap && (gap.usable.length > 0 || gap.lacking_must.length > 0 || gap.lacking_nice.length > 0) && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">What stands between this draft and a higher score</CardTitle>
              <CardDescription>
                Scores here are estimates. Nothing is added for you: these are facts you can use, and gaps only you can close.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              {gap.usable.length > 0 && (
                <div className="space-y-2">
                  <p className="font-medium">
                    Your library already covers {gap.usable.length} missing term{gap.usable.length === 1 ? "" : "s"}
                    <span className="font-normal text-muted-foreground">: adding them could lift the score to about {gap.usable_score}</span>
                  </p>
                  {gap.usable.map((u) => (
                    <div key={u.term} className="flex flex-wrap items-start gap-2 rounded-md bg-muted/40 p-2 sm:flex-nowrap">
                      <span className="shrink-0 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium">{u.term}</span>
                      <span className="min-w-0 basis-full text-muted-foreground sm:basis-auto sm:flex-1">
                        {u.from ? `${u.from.item}: ${u.from.bullet}` : "Mentioned in your library"}
                      </span>
                      {u.from && (
                        <Button
                          size="sm"
                          variant="secondary"
                          className="ml-auto"
                          onClick={() => {
                            if (addFromLibrary(u.from!)) toast.success("Added. Re-score to see the effect.");
                            else toast.info("That bullet is already there, or its role isn't in this draft.");
                          }}
                        >
                          Add
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {(gap.lacking_must.length > 0 || gap.lacking_nice.length > 0) && (
                <div className="space-y-2">
                  <p className="font-medium">
                    Not in your library
                    <span className="font-normal text-muted-foreground">
                      : if you gain these skills and add them to a resume, the score could reach about {gap.with_lacking_score}
                    </span>
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {gap.lacking_must.map((t) => (
                      <span key={t} className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-0.5 text-xs font-medium">{t} (required)</span>
                    ))}
                    {gap.lacking_nice.map((t) => (
                      <span key={t} className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs font-medium">{t}</span>
                    ))}
                  </div>
                  <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                    <Info className="mt-0.5 size-3.5 shrink-0" />
                    We never add skills you haven&apos;t shown. If you do have one, put it in a resume in your library and tailor again.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Layout */}
        <LayoutOptions value={options} onChange={setOptions} disabled={scoring} hint="Single column, plain text. Re-score to apply a change." />

        {/* Summary and skills */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Summary and skills</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              value={draft.summary}
              maxLength={1200}
              onChange={(e) => patch({ summary: e.target.value })}
              placeholder="Two sentences about your strongest fit for this job"
              className="min-h-[80px] text-sm"
              aria-label="Summary"
            />
            {Object.entries(draft.skills).map(([group, items]) => (
              <label key={group} className="block space-y-1 text-sm">
                <span className="font-medium">{group}</span>
                <Input
                  value={items.join(", ")}
                  onChange={(e) =>
                    patch({
                      skills: {
                        ...draft.skills,
                        [group]: e.target.value.split(",").map((s) => s.trimStart()),
                      },
                    })
                  }
                  onBlur={() =>
                    patch({
                      skills: { ...draft.skills, [group]: draft.skills[group].map((s) => s.trim()).filter(Boolean) },
                    })
                  }
                />
              </label>
            ))}
            {annotated && annotated.new_skills.length > 0 && (
              <p className="text-xs text-amber-700 dark:text-amber-400">
                Not in your library: {annotated.new_skills.join(", ")}. Keep only what you can speak to in an interview.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Experience */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Experience</CardTitle>
            <CardDescription>Reorder roles, rewrite or reorder bullets, and see where each bullet came from.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {draft.experience.map((role, i) => {
              const meta = roleInfo(role.company);
              return (
                <section key={`${role.company}-${i}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="break-words font-semibold">{role.company}</p>
                      <p className="break-words text-sm text-muted-foreground">{[role.title, role.dates].filter(Boolean).join(" · ")}</p>
                    </div>
                    <div className="flex shrink-0">
                      <Button size="icon" variant="ghost" className="size-8" disabled={i === 0} aria-label="Move role up"
                        onClick={() => patch({ experience: move(draft.experience, i, -1) })}>
                        <ArrowUp className="size-4" />
                      </Button>
                      <Button size="icon" variant="ghost" className="size-8" disabled={i === draft.experience.length - 1} aria-label="Move role down"
                        onClick={() => patch({ experience: move(draft.experience, i, 1) })}>
                        <ArrowDown className="size-4" />
                      </Button>
                    </div>
                  </div>
                  <ItemBullets
                    generationId={generationId}
                    kind="experience"
                    name={role.company}
                    bullets={role.bullets}
                    infoFor={infoIn(meta?.bullets)}
                    unused={meta?.unused ?? []}
                    onChange={(bullets) => setRole(i, bullets)}
                  />
                </section>
              );
            })}
          </CardContent>
        </Card>

        {/* Projects */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Projects</CardTitle>
            <CardDescription>Drop a project, change the order, or bring back one the writer left out.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {draft.projects.length === 0 && <p className="text-sm text-muted-foreground">No projects in this draft.</p>}
            {draft.projects.map((proj, i) => {
              const meta = projectInfo(proj.name);
              return (
                <section key={`${proj.name}-${i}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="break-words font-semibold">{proj.name}</p>
                      {proj.tech && <p className="break-words text-sm text-muted-foreground">{proj.tech}</p>}
                    </div>
                    <div className="flex shrink-0">
                      <Button size="icon" variant="ghost" className="size-8" disabled={i === 0} aria-label="Move project up"
                        onClick={() => patch({ projects: move(draft.projects, i, -1) })}>
                        <ArrowUp className="size-4" />
                      </Button>
                      <Button size="icon" variant="ghost" className="size-8" disabled={i === draft.projects.length - 1} aria-label="Move project down"
                        onClick={() => patch({ projects: move(draft.projects, i, 1) })}>
                        <ArrowDown className="size-4" />
                      </Button>
                      <Button size="icon" variant="ghost" className="size-8 text-muted-foreground hover:text-destructive" aria-label={`Remove ${proj.name}`}
                        onClick={() => patch({ projects: draft.projects.filter((_, j) => j !== i) })}>
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </div>
                  <ItemBullets
                    generationId={generationId}
                    kind="project"
                    name={proj.name}
                    bullets={proj.bullets}
                    infoFor={infoIn(meta?.bullets)}
                    unused={meta?.unused ?? []}
                    onChange={(bullets) => setProject(i, bullets)}
                  />
                </section>
              );
            })}

            {annotated && annotated.left_out_projects.length > 0 && (
              <div className="space-y-2 border-t pt-4">
                <p className="text-sm font-medium">In your library, not in this draft</p>
                {annotated.left_out_projects
                  .filter((p) => !draft.projects.some((d) => d.name === p.name))
                  .map((p) => (
                    <div key={p.name} className="flex items-center justify-between gap-2 rounded-md bg-muted/40 p-2 text-sm">
                      <span className="min-w-0 truncate">{p.name}{p.tech ? ` · ${p.tech}` : ""}</span>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={draft.projects.length >= 12}
                        onClick={() => patch({ projects: [...draft.projects, { name: p.name, tech: p.tech, link: "", bullets: p.bullets.slice(0, 3) }] })}
                      >
                        <Plus className="size-3.5" />
                        Add
                      </Button>
                    </div>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Score details and honesty checks */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Score details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <ScoreReport report={detail.report} threshold={detail.threshold} />
            {detail.details.warnings.length > 0 && (
              <details className="rounded-lg border bg-muted/30 text-sm" open={detail.details.warnings.length <= 3}>
                <summary className="cursor-pointer px-3 py-2 font-medium">
                  Honesty checks ({new Set(detail.details.warnings).size})
                </summary>
                <ul className="list-disc space-y-1 px-8 pb-3 text-muted-foreground">
                  {[...new Set(detail.details.warnings)].map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </details>
            )}
          </CardContent>
        </Card>

        {/* Cover letter and recruiter message, written from this draft */}
        <div ref={outreachRef} id="outreach" className="scroll-mt-4">
          <OutreachPanel
            key={version}
            generationId={generationId}
            company={detail.company ?? undefined}
            jobTitle={detail.job_title ?? undefined}
            saved={detail.outreach}
          />
        </div>
      </div>
    </div>
  );
}
