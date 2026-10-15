"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

/**
 * One line of text cut off with "…"; hovering shows the whole text in a small tooltip.
 * The tooltip only appears when the text is actually cut off, and is rendered on the page body so a
 * card's overflow can't clip it.
 */
export function TruncatedText({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number; width: number } | null>(null);

  const show = () => {
    const el = ref.current;
    if (!el || el.scrollWidth <= el.clientWidth) return;
    const r = el.getBoundingClientRect();
    setPos({ left: r.left, top: r.top, width: r.width });
  };
  const hide = () => setPos(null);

  // A fixed tooltip would stay behind if the page scrolls under the pointer
  useEffect(() => {
    if (!pos) return;
    window.addEventListener("scroll", hide, { capture: true, passive: true });
    return () => window.removeEventListener("scroll", hide, { capture: true });
  }, [pos]);

  return (
    <>
      <p
        ref={ref}
        className={cn("truncate", className)}
        onMouseEnter={show}
        onMouseLeave={hide}
      >
        {text}
      </p>
      {pos &&
        createPortal(
          <div
            role="tooltip"
            className="pointer-events-none fixed z-50 max-w-sm -translate-y-full break-words rounded-lg border bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground shadow-md"
            style={{ left: pos.left, top: pos.top - 6, minWidth: Math.min(pos.width, 240) }}
          >
            {text}
          </div>,
          document.body
        )}
    </>
  );
}
