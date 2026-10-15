"use client";

import { useState, useEffect } from "react";
import { AlertCircle, CheckCircle2, Cpu, Database, Loader2, RefreshCw, Server, Sparkles, XCircle } from "lucide-react";
import { BACKEND_OVERRIDE_ALLOWED, getApiBase } from "@/lib/api/client";
import { useHealth } from "@/lib/hooks/use-health";
import { ClaudeCheck } from "@/components/settings/claude-check";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

const HEALTHY = ["connected", "healthy", "ok", "online", "true"];

/** Status text with a green tick or a red cross; only these exact words count as healthy ("not_connected" doesn't). */
function StatusBadge({ status }: { status: string }) {
  const isHealthy = HEALTHY.includes(status.trim().toLowerCase());
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
        isHealthy ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" : "bg-destructive/10 text-destructive"
      )}
    >
      {isHealthy ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function SettingsPanel() {
  const { health, loading, refreshing, error, refetch } = useHealth();
  const [urlInput, setUrlInput] = useState("");

  useEffect(() => {
    setUrlInput(getApiBase());
  }, []);

  const handleSaveUrl = () => {
    if (!urlInput.trim()) return;
    localStorage.setItem("rag_backend_url", urlInput.trim());
    toast.success("API URL updated successfully");
    void refetch();
  };

  const services = [
    { label: "Backend", icon: Server, status: health?.backend },
    ...(health?.groq ? [{ label: "Groq", icon: Cpu, status: health.groq }] : []),
    { label: "Google AI", icon: Sparkles, status: health?.gemini },
    { label: "Postgres", icon: Database, status: health?.postgres },
    { label: "Qdrant", icon: Database, status: health?.qdrant },
  ];

  const details = [
    { label: "Environment", value: health?.environment ?? "unknown" },
    { label: "Overall status", value: <StatusBadge status={health?.status ?? "unknown"} /> },
    ...(health?.version ? [{ label: "Version", value: health.version }] : []),
  ];

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="flex flex-row items-start justify-between gap-3 px-4 sm:px-5">
        <div>
          <CardTitle className="text-base">Services</CardTitle>
          <CardDescription>What the server is connected to right now</CardDescription>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          onClick={() => void refetch()}
          disabled={refreshing}
          aria-label="Check services again"
        >
          {refreshing ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 px-4 text-sm sm:px-5">
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="size-3.5 shrink-0" />
            <span className="min-w-0 flex-1">Can&apos;t reach the server: {error}</span>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {services.map((s) => (
            <div key={s.label} className="flex min-w-[11rem] flex-1 items-center justify-between gap-2 rounded-lg border bg-muted/20 px-3 py-2">
              <span className="flex min-w-0 items-center gap-2">
                <s.icon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium">{s.label}</span>
              </span>
              {loading ? <Skeleton className="h-4 w-14" /> : <StatusBadge status={s.status ?? "unknown"} />}
            </div>
          ))}
        </div>

        <dl className="flex flex-wrap items-center gap-x-6 gap-y-1.5 text-xs">
          {details.map((d) => (
            <div key={d.label} className="flex items-center gap-2">
              <dt className="text-muted-foreground">{d.label}</dt>
              <dd className="font-medium">{loading ? <Skeleton className="h-4 w-16" /> : d.value}</dd>
            </div>
          ))}
        </dl>

        <ClaudeCheck />

        {BACKEND_OVERRIDE_ALLOWED && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-3 text-xs">
            <span className="font-medium text-muted-foreground">API base URL</span>
            <Input
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="http://localhost:8000"
              className="h-8 max-w-xs font-mono text-xs"
            />
            <Button size="sm" className="h-8" onClick={handleSaveUrl}>
              Save
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
