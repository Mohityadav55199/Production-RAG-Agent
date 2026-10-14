"use client";

import { useRef, type KeyboardEvent } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon?: LucideIcon;
  badge?: number;
}

interface TabBarProps<T extends string> {
  tabs: readonly TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Used to link each tab to its panel; give panels id={panelId(prefix, tab)}. */
  idPrefix: string;
  label: string;
}

export const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
export const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

/** Tab list following the WAI-ARIA pattern: arrow keys, Home/End, roving tabindex. */
export function TabBar<T extends string>({ tabs, value, onChange, idPrefix, label }: TabBarProps<T>) {
  const refs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const index = tabs.findIndex((t) => t.id === value);
    let next = index;
    if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current.get(tabs[next].id)?.focus();
  };

  return (
    <div className="flex max-w-full overflow-x-auto">
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className="inline-flex rounded-lg border bg-background p-1"
      >
        {tabs.map(({ id, label: text, icon: Icon, badge }) => {
          const selected = id === value;
          return (
            <button
              key={id}
              ref={(el) => {
                if (el) refs.current.set(id, el);
                else refs.current.delete(id);
              }}
              type="button"
              role="tab"
              id={tabId(idPrefix, id)}
              aria-selected={selected}
              aria-controls={panelId(idPrefix, id)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(id)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                selected ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {Icon && <Icon className="size-4" />}
              {text}
              {badge ? <span className="rounded-full bg-background/20 px-1.5 text-xs">{badge}</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
