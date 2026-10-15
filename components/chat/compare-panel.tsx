"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeftRight, Check, Copy, FileCode2, ImagePlus, Library, Loader2, Square } from "lucide-react";
import { toast } from "sonner";
import { extractCodeFromImage, imageFilesFrom } from "@/lib/api/images";
import { parseSourceKey, streamCompare, type CompareSide } from "@/lib/api/sources";
import type { QuerySource } from "@/lib/types";
import { SourceSelect, useKnowledgeSources } from "@/components/chat/source-select";
import { CitationChips } from "@/components/chat/citation-chips";
import { Button } from "@/components/ui/button";
import { SafeMarkdown } from "@/components/ui/safe-markdown";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

type SideMode = "text" | "source";

interface SideState {
  mode: SideMode;
  text: string;
  label: string;
  sourceKey: string;
}

const FOCUS_PRESETS = [
  "Time and space complexity",
  "Correctness and edge cases",
  "Readability and style",
  "Which is better and why?",
];

const emptySide = (label: string): SideState => ({ mode: "text", text: "", label, sourceKey: "" });

function toRequestSide(side: SideState, name: string): CompareSide {
  if (side.mode === "text") {
    if (!side.text.trim()) throw new Error(`${name}: paste some code or text.`);
    return { type: "text", content: side.text, label: side.label.trim() || name };
  }
  const { project, documentId } = parseSourceKey(side.sourceKey);
  if (project) return { type: "project", project };
  if (documentId) return { type: "document", document_id: documentId };
  throw new Error(`${name}: choose a project or document.`);
}

export function ComparePanel() {
  const { sources } = useKnowledgeSources();
  const [left, setLeft] = useState<SideState>(emptySide("A"));
  const [right, setRight] = useState<SideState>(emptySide("B"));
  const [focus, setFocus] = useState("");
  const [result, setResult] = useState("");
  const [diff, setDiff] = useState<string | null>(null);
  const [usedSources, setUsedSources] = useState<QuerySource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const hasSources = sources.projects.length > 0 || sources.documents.length > 0;

  const run = async () => {
    let body;
    try {
      body = {
        left: toRequestSide(left, "Side A"),
        right: toRequestSide(right, "Side B"),
        focus: focus.trim() || undefined,
      };
    } catch (err) {
      toast.error((err as Error).message);
      return;
    }

    setRunning(true);
    setResult("");
    setDiff(null);
    setUsedSources([]);
    setError(null);
    abortRef.current = new AbortController();

    try {
      await streamCompare(
        body,
        {
          onToken: (t) => setResult((prev) => prev + t),
          onSources: setUsedSources,
          onDiff: setDiff,
          onDone: () => {},
          onError: (e) => setError(e.message),
        },
        abortRef.current.signal
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "Comparison failed");
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setRunning(false);
  };

  const swap = () => {
    setLeft(right);
    setRight(left);
  };

  const copyResult = () => {
    navigator.clipboard.writeText(result);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Compare code</CardTitle>
          <CardDescription>
            Paste two solutions (C++, Java, Python, DSA…), or pick imported repos or documents. You get a
            line diff for pasted code plus a detailed AI comparison, including time and space complexity.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[1fr_auto_1fr]">
            <SideEditor name="A" side={left} onChange={setLeft} sources={sources} disabled={running} />
            <div className="flex items-center justify-center">
              <Button
                variant="ghost"
                size="icon"
                onClick={swap}
                disabled={running}
                aria-label="Swap sides"
                title="Swap sides"
              >
                <ArrowLeftRight className="size-4" />
              </Button>
            </div>
            <SideEditor name="B" side={right} onChange={setRight} sources={sources} disabled={running} />
          </div>

          {!hasSources && (
            <p className="text-xs text-muted-foreground">
              To compare repos or documents, first import them on the{" "}
              <Link href="/github" className="underline underline-offset-2">
                GitHub
              </Link>{" "}
              or{" "}
              <Link href="/rag" className="underline underline-offset-2">
                RAG Agent
              </Link>{" "}
              page.
            </p>
          )}

          <div className="flex flex-wrap gap-1.5">
            {FOCUS_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                disabled={running}
                onClick={() => setFocus(preset)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  focus === preset
                    ? "border-primary bg-primary/10 text-primary"
                    : "text-muted-foreground hover:border-primary/40 hover:text-foreground"
                )}
              >
                {preset}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="Optional focus, e.g. 'authentication approach', 'performance', 'which is easier to maintain?'"
              disabled={running}
              className="flex-1"
            />
            {running ? (
              <Button variant="outline" onClick={stop}>
                <Square className="size-4" />
                Stop
              </Button>
            ) : (
              <Button onClick={run}>
                <ArrowLeftRight className="size-4" />
                Compare
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {(running || result || error || diff !== null) && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">Comparison result</CardTitle>
            {result && !running && (
              <Button variant="ghost" size="sm" onClick={copyResult}>
                {copied ? <Check className="size-4 text-emerald-500" /> : <Copy className="size-4" />}
                Copy
              </Button>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {diff !== null && (
              <details className="rounded-lg border bg-muted/30" open={diff.length < 4000}>
                <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
                  Line diff {diff ? "" : "(no differences)"}
                </summary>
                {diff && (
                  <pre className="max-h-96 overflow-auto px-3 pb-3 text-xs leading-relaxed">
                    {diff.split("\n").map((line, i) => (
                      <div
                        key={i}
                        className={cn(
                          line.startsWith("+") && !line.startsWith("+++") && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                          line.startsWith("-") && !line.startsWith("---") && "bg-rose-500/10 text-rose-700 dark:text-rose-400",
                          line.startsWith("@@") && "text-sky-600 dark:text-sky-400"
                        )}
                      >
                        {line || " "}
                      </div>
                    ))}
                  </pre>
                )}
              </details>
            )}

            {running && !result && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Analysing both sides…
              </div>
            )}

            {result && (
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <SafeMarkdown>{result}</SafeMarkdown>
              </div>
            )}

            {error && <p className="text-sm text-destructive">{error}</p>}

            {usedSources.length > 0 && !running && (
              <CitationChips sources={usedSources} className="mt-3" />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

interface SideEditorProps {
  name: string;
  side: SideState;
  onChange: (side: SideState) => void;
  sources: ReturnType<typeof useKnowledgeSources>["sources"];
  disabled?: boolean;
}

function SideEditor({ name, side, onChange, sources, disabled }: SideEditorProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);

  // Screenshot of code -> text in the box. The user reviews and edits it before comparing.
  const readScreenshot = async (file: File) => {
    setReading(true);
    try {
      const result = await extractCodeFromImage(file);
      onChange({
        ...side,
        text: result.text,
        // The default name ("A"/"B") counts as unnamed; a name the user typed is kept
        label: side.label && side.label !== name ? side.label : result.language ? `${result.language} snippet` : side.label,
      });
      if (result.note) toast.warning(result.note, { duration: 8000 });
      else toast.success("Code read from the screenshot. Check it, then compare.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not read the screenshot.");
    } finally {
      setReading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="min-w-0 space-y-2 rounded-xl border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">Side {name}</span>
        <div className="inline-flex rounded-lg border p-0.5">
          {(
            [
              { id: "text", label: "Paste code/text", icon: FileCode2 },
              { id: "source", label: "Repo / document", icon: Library },
            ] as const
          ).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              disabled={disabled}
              onClick={() => onChange({ ...side, mode: id })}
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors",
                side.mode === id
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="size-3" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {side.mode === "text" ? (
        <>
          <div className="flex items-center gap-2">
            <Input
              value={side.label}
              onChange={(e) => onChange({ ...side, label: e.target.value })}
              placeholder={`Name for side ${name} (e.g. solution_a.cpp)`}
              disabled={disabled}
              className="h-8 flex-1 text-xs"
            />
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              data-testid={`code-image-input-${name}`}
              onChange={(e) => e.target.files?.[0] && void readScreenshot(e.target.files[0])}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 shrink-0 gap-1.5 text-xs"
              disabled={disabled || reading}
              onClick={() => fileRef.current?.click()}
              title="Read the code from a screenshot (you can also paste or drop an image into the box)"
            >
              {reading ? <Loader2 className="size-3.5 animate-spin" /> : <ImagePlus className="size-3.5" />}
              {reading ? "Reading…" : "From screenshot"}
            </Button>
          </div>
          <Textarea
            value={side.text}
            onChange={(e) => onChange({ ...side, text: e.target.value })}
            onPaste={(e) => {
              const files = imageFilesFrom(e.clipboardData);
              if (files.length > 0) {
                e.preventDefault();
                void readScreenshot(files[0]);
              }
            }}
            onDragOver={(e) => Array.from(e.dataTransfer.types).includes("Files") && e.preventDefault()}
            onDrop={(e) => {
              const files = imageFilesFrom(e.dataTransfer);
              if (files.length > 0) {
                e.preventDefault();
                void readScreenshot(files[0]);
              }
            }}
            placeholder="Paste code or text here, or paste or drop a screenshot of code…"
            disabled={disabled || reading}
            spellCheck={false}
            className="min-h-[220px] font-mono text-xs"
          />
        </>
      ) : (
        <SourceSelect
          value={side.sourceKey}
          onChange={(v) => onChange({ ...side, sourceKey: v })}
          sources={sources}
          disabled={disabled}
          className="w-full"
        />
      )}
    </div>
  );
}
