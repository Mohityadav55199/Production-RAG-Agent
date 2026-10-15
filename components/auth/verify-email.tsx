"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Brain, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/context/auth-context";
import { Button } from "@/components/ui/button";

type State = { kind: "working" } | { kind: "done"; email: string } | { kind: "failed"; message: string };

/** Opened from the confirmation email: works whether or not this browser is signed in. */
export function VerifyEmail() {
  const token = useSearchParams().get("token");
  const { status, markVerified } = useAuth();
  const [state, setState] = useState<State>(
    token ? { kind: "working" } : { kind: "failed", message: "This link is missing its code. Open it from the email again." }
  );
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true; // the token is single-purpose; don't post it twice (React dev mode runs effects twice)
    apiFetch<{ ok: boolean; email: string }>("/auth/verify-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then((r) => {
        setState({ kind: "done", email: r.email });
        markVerified();
      })
      .catch((err) => setState({ kind: "failed", message: err instanceof Error ? err.message : "Could not confirm your email." }));
  }, [token, markVerified]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-background px-6 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
        <Brain className="size-6" />
      </div>
      {state.kind === "working" && (
        <p className="flex items-center gap-2 text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" />
          Confirming your email…
        </p>
      )}
      {state.kind === "done" && (
        <div className="max-w-sm space-y-3">
          <CheckCircle2 className="mx-auto size-8 text-emerald-500" />
          <p className="font-medium">Email confirmed</p>
          <p className="text-sm text-muted-foreground">{state.email} is ready to use.</p>
          <Button asChild>
            <Link href={status === "authed" ? "/rag" : "/login"}>{status === "authed" ? "Open the app" : "Log in"}</Link>
          </Button>
        </div>
      )}
      {state.kind === "failed" && (
        <div className="max-w-sm space-y-3">
          <XCircle className="mx-auto size-8 text-destructive" />
          <p className="font-medium">We couldn&apos;t confirm your email</p>
          <p className="text-sm text-muted-foreground">{state.message}</p>
          <Button asChild variant="outline">
            <Link href={status === "authed" ? "/rag" : "/login"}>
              {status === "authed" ? "Back to the app (you can send a new link there)" : "Log in to get a new link"}
            </Link>
          </Button>
        </div>
      )}
    </div>
  );
}
