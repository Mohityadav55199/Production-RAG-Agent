"use client";

import { useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/context/auth-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface MetricsSummary {
  days: number;
  questions: number;
  errors: number;
  cancelled: number;
  fallback_rate: number;
  latency_ms: {
    total_p50: number | null;
    total_p95: number | null;
    first_token_p50: number | null;
    first_token_p95: number | null;
    retrieval_p50: number | null;
  };
  models: {
    provider: string | null;
    model: string | null;
    questions: number;
    avg_total_ms: number | null;
    avg_first_token_ms: number | null;
    input_tokens: number;
    output_tokens: number;
    errors: number;
  }[];
}

const RANGES = [1, 7, 30] as const;

const seconds = (ms: number | null | undefined) => (ms == null ? "–" : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`);

/** Administrator-only: how fast answers are, which models served them and what they cost in tokens. */
export function UsageMetrics() {
  const { user } = useAuth();
  const [days, setDays] = useState<(typeof RANGES)[number]>(7);
  const [data, setData] = useState<MetricsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!user?.is_admin) return;
    let cancelled = false;
    apiFetch<MetricsSummary>(`/admin/metrics?days=${days}`)
      .then((d) => !cancelled && (setData(d), setError(null)))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load metrics"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [user?.is_admin, days, reload]);

  if (!user?.is_admin) return null;

  const tiles = data
    ? [
        { label: "Questions", value: data.questions.toLocaleString() },
        { label: "Answer time (median)", value: seconds(data.latency_ms.total_p50), hint: `slowest 5%: ${seconds(data.latency_ms.total_p95)}` },
        { label: "First word (median)", value: seconds(data.latency_ms.first_token_p50), hint: `slowest 5%: ${seconds(data.latency_ms.first_token_p95)}` },
        { label: "Search time (median)", value: seconds(data.latency_ms.retrieval_p50) },
        {
          label: "Errors",
          value: data.errors.toLocaleString(),
          hint: data.questions ? `${((data.errors / data.questions) * 100).toFixed(1)}% of questions` : undefined,
          warn: data.errors > 0,
        },
        { label: "Answered by a fallback model", value: `${(data.fallback_rate * 100).toFixed(1)}%`, warn: data.fallback_rate > 0.2 },
      ]
    : [];

  return (
    <Card className="mt-4 gap-3 py-4">
      <CardHeader className="px-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="size-4" />
              Usage and speed
              <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">Admin</span>
            </CardTitle>
            <CardDescription>Every chat question, across all users. No question or answer text is stored here.</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg border p-0.5" role="group" aria-label="Time range">
              {RANGES.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => {
                    setLoading(true);
                    setDays(d);
                  }}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-medium",
                    days === d ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {d === 1 ? "24 h" : `${d} days`}
                </button>
              ))}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              aria-label="Refresh metrics"
              onClick={() => {
                setLoading(true);
                setReload((n) => n + 1);
              }}
            >
              {loading ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-4 sm:px-5">
        {error && <p className="text-sm text-destructive">{error}</p>}
        {data && data.questions === 0 && <p className="text-sm text-muted-foreground">No questions in this period yet.</p>}
        {data && data.questions > 0 && (
          <>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
              {tiles.map((t) => (
                <div key={t.label} className="rounded-lg border bg-muted/20 px-3 py-2">
                  <p className="truncate text-[11px] text-muted-foreground" title={t.label}>{t.label}</p>
                  <p className={cn("text-base font-semibold tabular-nums", t.warn && "text-amber-600 dark:text-amber-400")}>{t.value}</p>
                  {t.hint && <p className="text-[11px] text-muted-foreground">{t.hint}</p>}
                </div>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[34rem] text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Model</th>
                    <th className="py-2 pr-3 text-right font-medium">Questions</th>
                    <th className="py-2 pr-3 text-right font-medium">Avg answer</th>
                    <th className="py-2 pr-3 text-right font-medium">Avg first word</th>
                    <th className="py-2 pr-3 text-right font-medium">Tokens in / out</th>
                    <th className="py-2 text-right font-medium">Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {data.models.map((m) => (
                    <tr key={`${m.provider}-${m.model}`} className="border-b last:border-0">
                      <td className="py-2 pr-3">
                        <span className="font-medium">{m.model ?? "Not recorded"}</span>
                        {m.provider && <span className="ml-1.5 text-xs text-muted-foreground">{m.provider}</span>}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{m.questions.toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{seconds(m.avg_total_ms)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{seconds(m.avg_first_token_ms)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">
                        {m.input_tokens.toLocaleString()} / {m.output_tokens.toLocaleString()}
                      </td>
                      <td className="py-2 text-right tabular-nums">{m.errors.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
