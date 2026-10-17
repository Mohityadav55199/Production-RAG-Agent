"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Brain, Eye, EyeOff, Loader2 } from "lucide-react";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/context/auth-context";
import { useServerStatus } from "@/lib/context/server-status-context";

interface AuthFormProps {
  mode: "login" | "signup";
}

const COPY = {
  login: {
    title: "Welcome back",
    description: "Log in to your documents, code projects and resumes.",
    submit: "Log in",
    busy: "Logging in…",
    switchText: "New here?",
    switchLink: "Create an account",
    switchHref: "/signup",
  },
  signup: {
    title: "Create your account",
    description: "Your documents, projects and resumes stay private to your account.",
    submit: "Create account",
    busy: "Creating account…",
    switchText: "Already have an account?",
    switchLink: "Log in",
    switchHref: "/login",
  },
} as const;

export function AuthForm({ mode }: AuthFormProps) {
  const copy = COPY[mode];
  const router = useRouter();
  const { status, login, signup } = useAuth();
  const { isWaking, elapsedSeconds } = useServerStatus();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busySeconds, setBusySeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "authed") router.replace("/rag");
  }, [status, router]);

  // Track elapsed time during login/signup attempt to reassure users
  useEffect(() => {
    if (!busy) {
      setBusySeconds(0);
      return;
    }
    const interval = setInterval(() => {
      setBusySeconds((s) => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [busy]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (mode === "signup") {
      if (password.length < 8) return setError("Password must be at least 8 characters.");
      if (password !== confirm) return setError("Passwords do not match.");
    }
    setBusy(true);
    try {
      await (mode === "login" ? login : signup)(email.trim(), password);
      router.replace("/rag");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 right-0 h-[500px] w-[500px] rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute -bottom-40 left-0 h-[400px] w-[400px] rounded-full bg-violet-500/5 blur-3xl" />
      </div>
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>

      <div className="relative w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
            <Brain className="size-6" />
          </div>
          <span className="text-xl font-semibold tracking-tight">RAG Agent</span>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{copy.title}</CardTitle>
            <CardDescription>{copy.description}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="email" className="text-sm font-medium">Email</label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  disabled={busy}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="password" className="text-sm font-medium">Password</label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete={mode === "login" ? "current-password" : "new-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={mode === "signup" ? "At least 8 characters" : "Your password"}
                    required
                    disabled={busy}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((s) => !s)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </div>

              {mode === "signup" && (
                <div className="space-y-1.5">
                  <label htmlFor="confirm" className="text-sm font-medium">Confirm password</label>
                  <Input
                    id="confirm"
                    type={showPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="Repeat your password"
                    required
                    disabled={busy}
                  />
                </div>
              )}

              {isWaking && !busy && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-800 dark:text-amber-200 space-y-0.5">
                  <p className="font-semibold flex items-center gap-1.5 text-amber-900 dark:text-amber-100">
                    <Loader2 className="size-3.5 animate-spin text-amber-600 dark:text-amber-400" />
                    Render backend is waking up {elapsedSeconds > 0 ? `(~${elapsedSeconds}s)` : ""}
                  </p>
                  <p className="text-[11px] leading-relaxed text-amber-800/90 dark:text-amber-300/90">
                    Free tier instances sleep after inactivity. You can fill the form and submit; it will connect as soon as the server boots!
                  </p>
                </div>
              )}

              {error && (
                <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}

              {busy && busySeconds >= 2 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-800 dark:text-amber-200 space-y-0.5">
                  <p className="font-semibold flex items-center gap-1.5 text-amber-900 dark:text-amber-100">
                    <Loader2 className="size-3.5 animate-spin text-amber-600 dark:text-amber-400" />
                    Cold-starting server ({busySeconds}s elapsed)…
                  </p>
                  <p className="text-[11px] leading-relaxed text-amber-800/90 dark:text-amber-300/90">
                    Please don&apos;t refresh. Render free tier takes ~50s for the initial boot. You will be logged in immediately when ready.
                  </p>
                </div>
              )}

              <Button type="submit" className="w-full" disabled={busy || !email.trim() || !password}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                {busy ? (busySeconds >= 3 ? `Waking Render (${busySeconds}s)…` : copy.busy) : copy.submit}
              </Button>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-sm text-muted-foreground">
          {copy.switchText}{" "}
          <Link href={copy.switchHref} className="font-medium text-primary underline-offset-4 hover:underline">
            {copy.switchLink}
          </Link>
        </p>
      </div>
    </div>
  );
}
