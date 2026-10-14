"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Brain, Loader2, ServerOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/context/auth-context";

/** Renders children only for a logged-in user; everyone else is sent to the login page. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, retry } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "anon") router.replace("/login");
  }, [status, router]);

  if (status === "authed") return <>{children}</>;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
        <Brain className="size-6" />
      </div>

      {status === "unreachable" ? (
        <>
          <ServerOff className="size-6 text-muted-foreground" aria-hidden />
          <div className="max-w-sm space-y-1">
            <p className="font-medium">Can&apos;t reach the server</p>
            <p className="text-sm text-muted-foreground">
              You&apos;re still signed in. The server may be down or still starting. If the backend address
              changed, update it in{" "}
              <Link href="/settings" className="underline underline-offset-2">
                Settings
              </Link>
              .
            </p>
          </div>
          <Button onClick={retry}>Try again</Button>
        </>
      ) : (
        <>
          <Loader2 className="size-5 animate-spin text-muted-foreground" aria-label="Loading" />
          {status === "waking" && (
            <div className="max-w-sm space-y-1" role="status">
              <p className="font-medium">Waking up the server…</p>
              <p className="text-sm text-muted-foreground">
                Free hosting sleeps when idle, so the first visit can take up to a minute. You&apos;re still
                signed in.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
