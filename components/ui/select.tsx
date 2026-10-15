"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SelectOption<T extends string | number> {
  value: T;
  label: string;
  /** Shown on the button instead of the label (e.g. a shorter form). */
  short?: string;
}

interface SelectProps<T extends string | number> {
  value: T;
  onChange: (value: T) => void;
  options: readonly SelectOption<T>[];
  /** Accessible name, since the visible label usually sits outside the control. */
  label: string;
  disabled?: boolean;
  size?: "sm" | "md";
  className?: string;
  /** Classes for the button only (e.g. a coloured status pill). */
  buttonClassName?: string;
}

/** Styled single-choice dropdown (replaces the native <select>), with full keyboard support. */
export function Select<T extends string | number>({
  value,
  onChange,
  options,
  label,
  disabled,
  size = "md",
  className,
  buttonClassName,
}: SelectProps<T>) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const selected = options.find((o) => o.value === value);

  const close = useCallback((focusTrigger = false) => {
    setOpen(false);
    if (focusTrigger) triggerRef.current?.focus();
  }, []);

  const openList = () => {
    if (disabled) return;
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
  };

  const choose = (option: SelectOption<T> | undefined) => {
    if (!option) return;
    if (option.value !== value) onChange(option.value);
    close(true);
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDown);
    listRef.current?.focus();
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, close]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        openList();
      }
      return;
    }
    const moves: Record<string, () => void> = {
      ArrowDown: () => setActive((i) => Math.min(options.length - 1, i + 1)),
      ArrowUp: () => setActive((i) => Math.max(0, i - 1)),
      Home: () => setActive(0),
      End: () => setActive(options.length - 1),
      Enter: () => choose(options[active]),
      " ": () => choose(options[active]),
      Escape: () => close(true),
    };
    if (moves[e.key]) {
      e.preventDefault();
      moves[e.key]();
    } else if (e.key === "Tab") {
      close();
    }
  };

  return (
    <div ref={rootRef} className={cn("relative inline-block", className)} onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => (open ? close() : openList())}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${label}: ${selected?.label ?? ""}`}
        className={cn(
          "flex w-full items-center justify-between gap-1.5 rounded-md border border-input bg-background text-left outline-none transition-colors hover:bg-muted/50",
          "focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50",
          size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-2.5 text-sm",
          buttonClassName
        )}
      >
        <span className="truncate">{selected?.short ?? selected?.label}</span>
        <ChevronDown className={cn("size-3.5 shrink-0 opacity-60 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          tabIndex={-1}
          aria-label={label}
          aria-activedescendant={`${listId}-${active}`}
          className="absolute left-0 top-full z-50 mt-1 max-h-64 w-max min-w-full overflow-y-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg outline-none"
        >
          {options.map((option, i) => {
            const isSelected = option.value === value;
            return (
              <li
                key={String(option.value)}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={isSelected}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(option)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5",
                  size === "sm" ? "text-xs" : "text-sm",
                  i === active && "bg-muted",
                  isSelected && "font-medium"
                )}
              >
                <span className="flex-1 whitespace-nowrap">{option.label}</span>
                <Check className={cn("size-3.5 shrink-0 text-primary", !isSelected && "invisible")} />
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
