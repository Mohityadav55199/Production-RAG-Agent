"use client";

import { useState } from "react";
import { Loader2, Network } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/context/auth-context";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface NetworkInfo {
  detected_client_ip: string;
  socket_address: string | null;
  trusted_proxy_hops: number;
  client_ip_header: string | null;
  headers: Record<string, string>;
  x_forwarded_for_entries: string[];
  how_to_check: string;
}

/** Administrator-only: shows how this request reached the server, so the proxy settings can be verified. */
export function NetworkCheck() {
  const { user } = useAuth();
  const [info, setInfo] = useState<NetworkInfo | null>(null);
  const [loading, setLoading] = useState(false);

  if (!user?.is_admin) return null;

  const run = async () => {
    setLoading(true);
    try {
      setInfo(await apiFetch<NetworkInfo>("/admin/network"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Network check failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Network className="size-4" />
          Network check
          <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">Admin</span>
        </CardTitle>
        <CardDescription>
          Shows the address the server detects for you. It feeds the sign-up and login abuse limits, so it should match
          your real public IP.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={run} disabled={loading} variant="outline" size="sm">
          {loading ? <Loader2 className="size-4 animate-spin" /> : <Network className="size-4" />}
          Check my connection
        </Button>

        {info && (
          <div className="space-y-3 text-sm">
            <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-[max-content_1fr]">
              <dt className="text-muted-foreground">Detected client IP</dt>
              <dd className="font-mono font-semibold">{info.detected_client_ip}</dd>
              <dt className="text-muted-foreground">Socket address (the proxy)</dt>
              <dd className="font-mono">{info.socket_address ?? "unknown"}</dd>
              <dt className="text-muted-foreground">Trusted proxy hops</dt>
              <dd className="font-mono">{info.trusted_proxy_hops}</dd>
              <dt className="text-muted-foreground">Client IP header</dt>
              <dd className="font-mono">{info.client_ip_header ?? "not set (using X-Forwarded-For)"}</dd>
            </dl>

            {Object.keys(info.headers).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">Proxy headers received</p>
                <pre className="overflow-x-auto rounded-lg border bg-muted/30 p-3 text-xs leading-relaxed">
                  {Object.entries(info.headers)
                    .map(([name, value]) => `${name}: ${value}`)
                    .join("\n")}
                </pre>
              </div>
            )}

            <p className="text-xs text-muted-foreground">{info.how_to_check}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
