"use client";

import type { RenderOptions, TemplateName } from "@/lib/api/resume";
import { cn } from "@/lib/utils";

const TEMPLATES: { id: TemplateName; label: string; hint: string }[] = [
  { id: "classic", label: "Classic", hint: "Summary, skills, then experience" },
  { id: "compact", label: "Compact", hint: "Tighter spacing, fits more on a page" },
  { id: "skills_first", label: "Skills first", hint: "Skills lead, good for career changers" },
];

const FONT_SIZES: RenderOptions["font_pt"][] = [10, 11, 12];
const MARGINS: RenderOptions["margin_in"][] = [0.5, 0.6, 0.75, 1];

interface LayoutOptionsProps {
  value: RenderOptions;
  onChange: (value: RenderOptions) => void;
  disabled?: boolean;
}

/** Every template is single-column plain text, the layout ATS parsers read best. */
export function LayoutOptions({ value, onChange, disabled }: LayoutOptionsProps) {
  const selectClass =
    "h-9 rounded-md border bg-background px-2 text-sm disabled:cursor-not-allowed disabled:opacity-50";
  return (
    <div className="space-y-3">
      <div role="radiogroup" aria-label="Template" className="grid gap-2 sm:grid-cols-3">
        {TEMPLATES.map((t) => (
          <button
            key={t.id}
            type="button"
            role="radio"
            aria-checked={value.template === t.id}
            disabled={disabled}
            onClick={() => onChange({ ...value, template: t.id })}
            className={cn(
              "rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              value.template === t.id ? "border-primary bg-primary/5" : "hover:bg-muted/50"
            )}
          >
            <span className="block text-sm font-medium">{t.label}</span>
            <span className="block text-xs text-muted-foreground">{t.hint}</span>
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          Font size
          <select
            className={selectClass}
            disabled={disabled}
            value={value.font_pt}
            onChange={(e) => onChange({ ...value, font_pt: Number(e.target.value) as RenderOptions["font_pt"] })}
          >
            {FONT_SIZES.map((n) => (
              <option key={n} value={n}>{n} pt</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          Margins
          <select
            className={selectClass}
            disabled={disabled}
            value={value.margin_in}
            onChange={(e) => onChange({ ...value, margin_in: Number(e.target.value) as RenderOptions["margin_in"] })}
          >
            {MARGINS.map((n) => (
              <option key={n} value={n}>{n} in</option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
