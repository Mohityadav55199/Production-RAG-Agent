"use client";

import { useState } from "react";
import { CheckCircle2, Loader2, Sparkles, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/context/auth-context";
import { Button } from "@/components/ui/button";

interface ClaudeCheckResult {
  configured: boolean;
  model: string;
  ok: boolean;
  error: string | null;
  note?: string;
}

/** Administrator-only: one real request to Claude with the server's key, and the reason if it fails. */
export function ClaudeCheck() {
  const { user } = useAuth();
  const [result, setResult] = useState<ClaudeCheckResult | null>(null);
  const [checking, setChecking] = useState(false);

  if (!user?.is_admin) return null;

  const run = async () => {
    setChecking(true);
    try {
      setResult(await apiFetch<ClaudeCheckResult>("/admin/claude", { timeout: 120000 }));
    } catch (err) {
      setResult({ configured: true, model: "", ok: false, error: err instanceof Error ? err.message : "Check failed" });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="space-y-1.5 border-t border-border/60 pt-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-3.5 text-muted-foreground" />
        <span className="font-medium">Claude</span>
        <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">Admin</span>
        {result &&
          (result.ok ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="size-3" /> working{result.model ? ` (${result.model})` : ""}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-md bg-destructive/10 px-1.5 py-0.5 text-[11px] font-medium text-destructive">
              <XCircle className="size-3" /> {result.configured ? "not working" : "no key"}
            </span>
          ))}
        <Button size="sm" variant="outline" className="ml-auto h-7 text-xs" onClick={run} disabled={checking}>
          {checking && <Loader2 className="size-3 animate-spin" />}
          {checking ? "Testing…" : "Test Claude"}
        </Button>
      </div>
      {result?.error && <p className="break-words text-destructive">{result.error}</p>}
      {result?.note && <p className="text-muted-foreground">{result.note}</p>}
      {!result && (
        <p className="text-muted-foreground">
          Sends one small request with the server&apos;s ANTHROPIC_API_KEY. Users never see Claude errors; Groq answers instead.
        </p>
      )}
    </div>
  );
}
