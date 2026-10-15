"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { getApiBase } from "@/lib/api/client";

/** Shown when the API does not answer quickly: free hosting puts an idle server to sleep and it takes up to a minute to start. */
const SLOW_AFTER_MS = 3000;
const RETRY_EVERY_MS = 3000;

export function WakingBanner() {
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const check = async () => {
      const slow = setTimeout(() => !cancelled && setWaking(true), SLOW_AFTER_MS);
      try {
        const res = await fetch(`${getApiBase()}/health`, { cache: "no-store" });
        if (res.ok) {
          clearTimeout(slow);
          if (!cancelled) setWaking(false);
          return;
        }
      } catch {
        // unreachable while the server boots: try again
      }
      clearTimeout(slow);
      if (!cancelled) {
        setWaking(true);
        timer = setTimeout(check, RETRY_EVERY_MS);
      }
    };
    void check();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  if (!waking) return null;
  return (
    <div role="status" className="relative z-10 flex items-center justify-center gap-2 bg-amber-500/15 px-4 py-2 text-sm text-amber-700 dark:text-amber-300">
      <Loader2 className="size-4 animate-spin" />
      The server is waking up after being idle. This can take up to a minute; everything works once it is ready.
    </div>
  );
}
