"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, FileCode2, FileText, LayoutTemplate, Loader2, Save, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import {
  deleteLayout,
  importLayout,
  listLayouts,
  saveLayout,
  type RenderOptions,
  type SavedLayout,
  type TemplateName,
} from "@/lib/api/resume";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";

const TEMPLATES: { id: TemplateName; label: string; hint: string }[] = [
  { id: "classic", label: "Classic", hint: "Summary, skills, then experience" },
  { id: "compact", label: "Compact", hint: "Tighter spacing, fits more on a page" },
  { id: "skills_first", label: "Skills first", hint: "Skills lead, good for career changers" },
  { id: "student", label: "Student", hint: "Education leads, ideal for students and new grads" },
];

const FONTS = [
  { value: "serif" as const, label: "Serif" },
  { value: "sans" as const, label: "Sans-serif" },
];
const FONT_SIZES = ([10, 11, 12] as const).map((n) => ({ value: n, label: `${n} pt` }));
const MARGINS = ([0.5, 0.6, 0.75, 1] as const).map((n) => ({ value: n, label: `${n} in` }));

const SOURCE_LABEL: Record<SavedLayout["source"], string> = {
  saved: "Saved",
  latex: "Your LaTeX template",
  pdf: "From your PDF",
};

interface LayoutOptionsProps {
  value: RenderOptions;
  onChange: (value: RenderOptions) => void;
  disabled?: boolean;
  /** One line under the summary, e.g. "Re-score to apply a change." */
  hint?: string;
}

/**
 * Built-in templates, your saved layouts, and layouts made from your own resume (.tex template or .pdf look).
 * Collapsed to a one-line summary until "Customize" is clicked.
 */
export function LayoutOptions({ value, onChange, disabled, hint }: LayoutOptionsProps) {
  const { confirm, dialog } = useConfirm();
  const [layouts, setLayouts] = useState<SavedLayout[]>([]);
  const [importing, setImporting] = useState(false);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [pastingLatex, setPastingLatex] = useState(false);
  const [latexCode, setLatexCode] = useState("");
  const [latexName, setLatexName] = useState("");
  const [saving, setSaving] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    listLayouts()
      .then((list) => !cancelled && setLayouts(list))
      .catch(() => {
        // Saved layouts are optional; the built-in templates still work
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const usingTemplate = layouts.find((l) => l.id === value.layout_id)?.has_template ?? Boolean(value.preamble);
  // Changing a built-in option leaves a saved layout (except a LaTeX template, whose look comes from the file)
  const change = (patch: Partial<RenderOptions>) =>
    onChange({ ...value, ...patch, ...(usingTemplate ? {} : { layout_id: null, layout_name: null }) });

  const apply = (layout: SavedLayout) => {
    onChange({ ...layout.options, layout_id: layout.id, layout_name: layout.name, preamble: null });
  };

  const onFile = async (file: File) => {
    setImporting(true);
    try {
      const layout = await importLayout(file);
      setLayouts((prev) => [layout, ...prev]);
      apply(layout);
      toast.success(`Layout "${layout.name}" created`, { description: layout.notes?.join(" · ") });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not read that file");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onPasteLatexSubmit = async () => {
    if (!latexCode.trim()) return;
    setImporting(true);
    try {
      const layout = await importLayout(null, latexName.trim() || "Pasted LaTeX layout", latexCode.trim());
      setLayouts((prev) => [layout, ...prev]);
      apply(layout);
      setPastingLatex(false);
      setLatexCode("");
      setLatexName("");
      toast.success(`Layout "${layout.name}" created`, { description: layout.notes?.join(" · ") });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not import that LaTeX code");
    } finally {
      setImporting(false);
    }
  };

  const save = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const layout = await saveLayout(name.trim(), value);
      setLayouts((prev) => [layout, ...prev]);
      apply(layout);
      setNaming(false);
      setName("");
      toast.success(`Saved "${layout.name}"`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the layout");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (layout: SavedLayout) => {
    if (!(await confirm({ title: `Delete the layout "${layout.name}"?`, description: "Resumes already made with it keep their look." }))) return;
    try {
      await deleteLayout(layout.id);
      setLayouts((prev) => prev.filter((l) => l.id !== layout.id));
      if (value.layout_id === layout.id) onChange({ ...value, layout_id: null, layout_name: null, preamble: null });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete");
    }
  };

  const templateLabel = TEMPLATES.find((t) => t.id === value.template)?.label ?? "Classic";
  const summary = usingTemplate
    ? `Your LaTeX template "${value.layout_name ?? "template"}"`
    : [value.layout_name, templateLabel, value.font === "sans" ? "Sans-serif" : "Serif", `${value.font_pt} pt`, `${value.margin_in} in margins`]
        .filter(Boolean)
        .join(" · ");

  return (
    <div className="rounded-xl border bg-muted/20">
      {/* Collapsed: one line saying what the resume will look like */}
      <div className="flex items-center gap-2 px-3 py-2">
        <LayoutTemplate className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm">
            <span className="font-medium">Layout</span>
            <span className="text-muted-foreground"> · {summary}</span>
          </p>
          {hint && <p className="truncate text-xs text-muted-foreground">{hint}</p>}
        </div>
        <Button size="sm" variant="ghost" className="h-7 shrink-0 text-xs" onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
          {expanded ? "Done" : "Customize"}
          <ChevronDown className={cn("size-3.5 transition-transform", expanded && "rotate-180")} />
        </Button>
      </div>

      {expanded && (
        <div className="space-y-4 border-t p-3">
          {/* Your own format */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">Your layouts</p>
              <div className="flex flex-wrap gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".tex,.pdf,application/pdf,application/x-tex,text/x-tex"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
                />
                <Button size="sm" variant="outline" disabled={disabled || importing} onClick={() => fileRef.current?.click()}>
                  {importing ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
                  Upload .tex/.pdf
                </Button>
                <Button size="sm" variant="outline" disabled={disabled || importing} onClick={() => setPastingLatex((v) => !v)}>
                  <FileCode2 className="size-3.5" />
                  Paste LaTeX
                </Button>
                <Button size="sm" variant="ghost" disabled={disabled} onClick={() => setNaming((v) => !v)}>
                  <Save className="size-3.5" />
                  Save layout
                </Button>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Paste or upload a <strong>.tex</strong> resume to use its LaTeX template, or upload a <strong>.pdf</strong> to copy its font,
              margins and section order. Your content is never taken from these files.
            </p>

            {pastingLatex && (
              <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold">Paste LaTeX template or preamble</span>
                  <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => setPastingLatex(false)}>
                    Cancel
                  </Button>
                </div>
                <Input
                  value={latexName}
                  onChange={(e) => setLatexName(e.target.value)}
                  maxLength={80}
                  placeholder="Template name, e.g. Overleaf Modern"
                  className="h-8 text-xs"
                />
                <Textarea
                  value={latexCode}
                  onChange={(e) => setLatexCode(e.target.value)}
                  placeholder={`\\documentclass[11pt,a4paper]{article}\n\\usepackage{geometry}\n% Paste your full LaTeX resume or preamble here...`}
                  className="max-h-[260px] min-h-[140px] overflow-y-auto font-mono text-xs leading-relaxed"
                />
                <Button
                  size="sm"
                  className="h-8 w-full text-xs"
                  disabled={importing || latexCode.trim().length < 40}
                  onClick={onPasteLatexSubmit}
                >
                  {importing ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : <FileCode2 className="mr-1.5 size-3.5" />}
                  Import LaTeX template
                </Button>
              </div>
            )}

            {naming && (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void save();
                }}
              >
                <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="Name, e.g. Two-page sans" className="h-9" autoFocus />
                <Button size="sm" type="submit" disabled={saving || !name.trim()}>
                  {saving && <Loader2 className="size-3.5 animate-spin" />}
                  Save
                </Button>
              </form>
            )}

            {layouts.length > 0 && (
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Saved layouts">
                {layouts.map((l) => {
                  const active = value.layout_id === l.id;
                  const Icon = l.source === "latex" ? FileCode2 : FileText;
                  return (
                    <div
                      key={l.id}
                      className={cn(
                        "group flex items-center gap-1 rounded-full border pl-3 pr-1 text-sm transition-colors",
                        active ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                      )}
                    >
                      <button
                        type="button"
                        role="radio"
                        aria-checked={active}
                        disabled={disabled}
                        onClick={() => apply(l)}
                        className="flex items-center gap-1.5 py-1.5"
                        title={SOURCE_LABEL[l.source]}
                      >
                        <Icon className="size-3.5 text-muted-foreground" />
                        <span className="max-w-[12rem] truncate font-medium">{l.name}</span>
                        <span className="hidden text-xs text-muted-foreground sm:inline">· {SOURCE_LABEL[l.source]}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(l)}
                        disabled={disabled}
                        className="rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                        aria-label={`Delete layout ${l.name}`}
                      >
                        <Trash2 className="size-3" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {usingTemplate && (
              <div className="flex items-start justify-between gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-xs">
                <span>
                  Using your LaTeX template <strong>{value.layout_name}</strong>. Its preamble styles the page; the built-in
                  options below don&apos;t apply. If it can&apos;t compile with your content, the built-in layout is used.
                </span>
                <button type="button" onClick={() => onChange({ ...value, layout_id: null, layout_name: null, preamble: null })} aria-label="Stop using the template" className="text-muted-foreground hover:text-foreground">
                  <X className="size-3.5" />
                </button>
              </div>
            )}
          </div>

          {/* Built-in options */}
          <fieldset disabled={disabled || usingTemplate} className={cn("space-y-3", usingTemplate && "opacity-50")}>
            <div role="radiogroup" aria-label="Template" className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  role="radio"
                  aria-checked={value.template === t.id}
                  onClick={() => change({ template: t.id })}
                  className={cn(
                    "rounded-lg border bg-background px-3 py-2 text-left transition-colors disabled:cursor-not-allowed",
                    value.template === t.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                  )}
                >
                  <span className="block text-sm font-medium">{t.label}</span>
                  <span className="block text-xs text-muted-foreground">{t.hint}</span>
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
              <span className="flex items-center gap-2">
                Font
                <Select label="Font" size="sm" className="w-28" value={value.font ?? "serif"} options={FONTS} onChange={(font) => change({ font })} disabled={disabled || usingTemplate} />
              </span>
              <span className="flex items-center gap-2">
                Size
                <Select label="Font size" size="sm" className="w-20" value={value.font_pt} options={FONT_SIZES} onChange={(font_pt) => change({ font_pt })} disabled={disabled || usingTemplate} />
              </span>
              <span className="flex items-center gap-2">
                Margins
                <Select label="Margins" size="sm" className="w-20" value={value.margin_in} options={MARGINS} onChange={(margin_in) => change({ margin_in })} disabled={disabled || usingTemplate} />
              </span>
            </div>
            {value.section_order && value.section_order.length > 0 && (
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                Section order: <span className="font-medium capitalize text-foreground">{value.section_order.join(" → ")}</span>
                <button type="button" className="underline underline-offset-2" onClick={() => change({ section_order: null })}>
                  Use the template&apos;s order
                </button>
              </p>
            )}
          </fieldset>
        </div>
      )}
      {dialog}
    </div>
  );
}
