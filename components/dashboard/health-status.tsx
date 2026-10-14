"use client";

import { motion } from "framer-motion";
import { CheckCircle2, XCircle, RefreshCw, Server } from "lucide-react";
import { useHealth } from "@/lib/hooks/use-health";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function HealthStatus({ compact = false }: { compact?: boolean }) {
  const { health, loading, refetch } = useHealth();

  const services = [
    { name: "Backend API", key: "backend", value: health?.backend },
    ...(health?.groq ? [{ name: "Groq LLM", key: "groq", value: health?.groq }] : []),
    { name: "Google Embeddings", key: "gemini", value: health?.gemini },
    { name: "PostgreSQL", key: "postgres", value: health?.postgres },
    { name: "Qdrant Vector DB", key: "qdrant", value: health?.qdrant },
  ];

  const getStatusColor = (val: string | undefined) => {
    const status = String(val ?? "unknown").toLowerCase();
    if (status === "connected" || status === "ok" || status === "healthy") {
      return "text-emerald-500 bg-emerald-500/10 border-emerald-500/20";
    }
    if (status === "not_connected" || status === "disconnected" || status === "failed") {
      return "text-rose-500 bg-rose-500/10 border-rose-500/20";
    }
    return "text-amber-500 bg-amber-500/10 border-amber-500/20";
  };

  const getStatusIcon = (val: string | undefined) => {
    const status = String(val ?? "unknown").toLowerCase();
    if (status === "connected" || status === "ok" || status === "healthy") {
      return <CheckCircle2 className="size-4" />;
    }
    if (status === "not_connected" || status === "disconnected" || status === "failed") {
      return <XCircle className="size-4" />;
    }
    return <RefreshCw className="size-4 animate-spin" />;
  };

  const isOnline = (v: string | undefined) =>
    ["connected", "ok", "healthy"].includes(String(v ?? "").toLowerCase());
  const offline = services.filter((s) => !isOnline(s.value));
  const summary = loading
    ? "Checking services…"
    : offline.length === 0
      ? "All systems operational"
      : `${offline.length} service${offline.length > 1 ? "s" : ""} need attention: ${offline.map((s) => s.name).join(", ")}`;

  if (compact) {
    return (
      <div className="flex flex-col gap-3 rounded-xl border bg-card px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-semibold">System Health</span>
          <span className={offline.length === 0 && !loading ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}>
            {summary}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {services.map((service) => (
            <span
              key={service.key}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${getStatusColor(service.value)}`}
              title={`${service.name}: ${isOnline(service.value) ? "Online" : "Needs attention"}`}
            >
              <span className={`size-1.5 rounded-full ${isOnline(service.value) ? "bg-emerald-500" : "bg-amber-500"}`} />
              <span className="text-foreground">{service.name}</span>
            </span>
          ))}
          <Button variant="ghost" size="icon" onClick={refetch} disabled={loading} className="size-7" aria-label="Refresh health">
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
    >
      <Card className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/5 via-transparent to-violet-500/5" />
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <div>
            <CardTitle className="text-base font-bold">System Health</CardTitle>
            <CardDescription
              className={offline.length === 0 && !loading ? "text-emerald-600" : "text-amber-600"}
            >
              {summary}
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={refetch}
            disabled={loading}
            className="size-8"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </CardHeader>
        <CardContent className="mt-2 grid gap-3 sm:grid-cols-2 md:grid-cols-4">
          {services.map((service) => (
            <div
              key={service.key}
              className={`flex items-center justify-between rounded-lg border px-3.5 py-2.5 text-sm transition-all duration-300 ${getStatusColor(
                service.value
              )}`}
            >
              <div className="flex items-center gap-2">
                <Server className="size-4 opacity-70" />
                <span className="font-medium text-foreground">{service.name}</span>
              </div>
              <div className="flex items-center gap-1.5 font-semibold capitalize">
                {getStatusIcon(service.value)}
                <span className="text-xs">
                  {service.value === "connected" || service.value === "ok" || service.value === "healthy"
                    ? "Online"
                    : service.value === "not_connected" || service.value === "disconnected" || service.value === "failed"
                      ? "Offline"
                      : "Unknown"}
                </span>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </motion.div>
  );
}
