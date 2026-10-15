"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, FileText, FolderGit2, Layers, Search } from "lucide-react";
import { getSources, type KnowledgeSources } from "@/lib/api/sources";
import { useApp } from "@/lib/context/app-context";
import { cn } from "@/lib/utils";

export function useKnowledgeSources() {
  const { refreshKey } = useApp();
  const [sources, setSources] = useState<KnowledgeSources>({ projects: [], documents: [] });
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      setSources(await getSources());
    } catch {
      // Older backends without /projects/sources: keep the "all" option only
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch, refreshKey]);

  return { sources, loading, refetch };
}

interface SourceSelectProps {
  value: string;
  onChange: (value: string) => void;
  sources: KnowledgeSources;
  includeAll?: boolean;
  allLabel?: string;
  /** Limit the list to code projects, uploaded documents, or both (default). */
  kind?: "documents" | "projects" | "both";
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

interface Option {
  value: string;
  label: string;
  detail?: string;
  icon: typeof FileText;
  disabled?: boolean;
}

interface Group {
  label?: string;
  options: Option[];
}

const SEARCH_FROM = 8; // show a filter box once the list is this long

/** Styled dropdown listing projects and documents; values are "all" | "project:<name>" | "document:<id>". */
export function SourceSelect({
  value,
  onChange,
  sources,
  includeAll = false,
  allLabel = "All documents & projects",
  kind = "both",
  placeholder = "Choose a project or document…",
  disabled,
  className,
}: SourceSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();

  const groups: Group[] = [];
  if (includeAll) groups.push({ options: [{ value: "all", label: allLabel, icon: Layers }] });
  if (kind !== "documents" && sources.projects.length > 0) {
    groups.push({
      label: "Code projects",
      options: sources.projects.map((p) => ({
        value: `project:${p.name}`, label: p.name, detail: `${p.file_count} files`, icon: FolderGit2,
      })),
    });
  }
  if (kind !== "projects" && sources.documents.length > 0) {
    groups.push({
      label: "Documents",
      options: sources.documents.map((d) => ({ value: `document:${d.id}`, label: d.filename, icon: FileText })),
    });
  }

  const all = groups.flatMap((g) => g.options);
  const selected = all.find((o) => o.value === value);
  const searchable = all.length > SEARCH_FROM;
  const q = query.trim().toLowerCase();
  const visibleGroups = groups
    .map((g) => ({ ...g, options: q ? g.options.filter((o) => o.label.toLowerCase().includes(q)) : g.options }))
    .filter((g) => g.options.length > 0);
  const visible = visibleGroups.flatMap((g) => g.options);

  const close = useCallback((focusTrigger = false) => {
    setOpen(false);
    setQuery("");
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  const openList = () => {
    if (disabled) return;
    setOpen(true);
    setActive(Math.max(0, all.findIndex((o) => o.value === value)));
  };

  const choose = (option: Option | undefined) => {
    if (!option || option.disabled) return;
    onChange(option.value);
    close(true);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDown);
    (searchable ? searchRef.current : listRef.current)?.focus();
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, close, searchable]);

  useEffect(() => {
    if (open) listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        openList();
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(visible.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(visible.length - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(visible[active]);
    } else if (e.key === "Tab") {
      close();
    }
  };

  const Icon = selected?.icon ?? Layers;
  let index = -1;

  return (
    <div
      ref={rootRef}
      className={cn("relative h-9 min-w-0 rounded-lg border border-input bg-background text-sm", className)}
      onKeyDown={onKeyDown}
    >
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => (open ? close() : openList())}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        className={cn(
          "flex h-full w-full min-w-0 items-center gap-2 rounded-[inherit] px-3 text-left outline-none",
          "focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50"
        )}
      >
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className={cn("min-w-0 flex-1 truncate", !selected && "text-muted-foreground")}>
          {selected?.label ?? placeholder}
        </span>
        <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-max min-w-full max-w-[min(26rem,calc(100vw-2rem))] overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-lg">
          {searchable && (
            <div className="flex items-center gap-2 border-b px-3 py-2">
              <Search className="size-3.5 text-muted-foreground" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                placeholder="Search…"
                aria-label="Search the list"
                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
          )}
          <ul
            ref={listRef}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-activedescendant={visible[active] ? `${listId}-${active}` : undefined}
            className="max-h-72 overflow-y-auto p-1 outline-none"
          >
            {visible.length === 0 && <li className="px-3 py-2 text-sm text-muted-foreground">No matches</li>}
            {visibleGroups.map((group, gi) => (
              <li key={group.label ?? `g${gi}`} role="presentation">
                {group.label && (
                  <p className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {group.label}
                  </p>
                )}
                <ul role="group" aria-label={group.label}>
                  {group.options.map((option) => {
                    index += 1;
                    const i = index;
                    const isSelected = option.value === value;
                    const OptionIcon = option.icon;
                    return (
                      <li
                        key={option.value}
                        id={`${listId}-${i}`}
                        data-index={i}
                        role="option"
                        aria-selected={isSelected}
                        onMouseEnter={() => setActive(i)}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => choose(option)}
                        title={option.label}
                        className={cn(
                          "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm",
                          i === active && "bg-muted",
                          isSelected && "font-medium"
                        )}
                      >
                        <OptionIcon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate">{option.label}</span>
                        {option.detail && <span className="shrink-0 text-xs text-muted-foreground">{option.detail}</span>}
                        <Check className={cn("size-4 shrink-0 text-primary", !isSelected && "invisible")} />
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
