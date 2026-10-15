"use client";

import { useState } from "react";
import { Loader2, MailCheck } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api/client";
import { useAuth } from "@/lib/context/auth-context";

/** Shown until the signed-in user confirms their email (only when the server requires it). */
export function VerifyEmailBanner() {
  const { user } = useAuth();
  const [sending, setSending] = useState(false);

  if (!user || user.email_verified !== false) return null;

  const resend = async () => {
    setSending(true);
    try {
      await apiFetch("/auth/resend-verification", { method: "POST" });
      toast.success(`Sent a new link to ${user.email}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not send the email");
    } finally {
      setSending(false);
    }
  };

  return (
    <div role="status" className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-800 dark:text-amber-300">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-1">
        <MailCheck className="size-4 shrink-0" />
        <span>
          Confirm your email to start using the app: we sent a link to <strong>{user.email}</strong>.
        </span>
        <button
          type="button"
          onClick={resend}
          disabled={sending}
          className="inline-flex items-center gap-1 font-medium underline underline-offset-2 disabled:opacity-60"
        >
          {sending && <Loader2 className="size-3.5 animate-spin" />}
          Send it again
        </button>
      </div>
    </div>
  );
}
