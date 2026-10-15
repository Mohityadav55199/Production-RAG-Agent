"use client";

import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Copy,
  FileCheck2,
  Linkedin,
  Mail,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import {
  generateCoverLetter,
  generateRecruiterMessage,
  type CoverLetterResult,
  type RecruiterMessageResult,
  type SavedOutreach,
} from "@/lib/api/resume";
import { cn, copyText } from "@/lib/utils";

type Platform = "linkedin" | "email";

interface OutreachPanelProps {
  generationId: string;
  company?: string;
  jobTitle?: string;
  /** Letters and messages already saved with this run (shown without calling the AI again). */
  saved?: SavedOutreach;
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** "Check before sending" notes, and a hint when the draft changed after the text was written. */
function Notes({ warnings, stale, onRegenerate }: { warnings?: string[]; stale?: boolean; onRegenerate: () => void }) {
  return (
    <>
      {stale && (
        <div className="flex flex-col gap-2 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 text-xs text-sky-700 dark:text-sky-400 sm:flex-row sm:items-center sm:justify-between">
          <span>You edited the draft after this was written, so it may mention things you removed.</span>
          <button onClick={onRegenerate} className="shrink-0 font-medium underline underline-offset-2">
            Rewrite from the current draft
          </button>
        </div>
      )}
      {warnings && warnings.length > 0 && (
        <div className="flex gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <div className="space-y-1">
            {warnings.map((w, i) => (
              <div key={i}>{w}</div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function Failure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive sm:flex-row sm:items-center sm:justify-between"
    >
      <span className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        {message}
      </span>
      <button
        onClick={onRetry}
        className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-destructive/30 bg-background px-3 py-1.5 text-xs font-medium hover:bg-destructive/10"
      >
        <RefreshCw className="h-3 w-3" />
        Try again
      </button>
    </div>
  );
}

export function OutreachPanel({ generationId, company, jobTitle, saved }: OutreachPanelProps) {
  const [activeTab, setActiveTab] = useState<"cover_letter" | "recruiter">("cover_letter");
  const [platform, setPlatform] = useState<Platform>("linkedin");

  const [coverLetter, setCoverLetter] = useState<CoverLetterResult | null>(saved?.cover_letter ?? null);
  const [messages, setMessages] = useState<Partial<Record<Platform, RecruiterMessageResult>>>(saved?.recruiter ?? {});
  const recruiterMsg = messages[platform] ?? null;

  const [loadingLetter, setLoadingLetter] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState(false);
  const [letterError, setLetterError] = useState<string | null>(null);
  const [msgError, setMsgError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchCoverLetter = async (regenerate = false) => {
    setLoadingLetter(true);
    setLetterError(null);
    try {
      setCoverLetter(await generateCoverLetter(generationId, regenerate));
    } catch (err) {
      const message = errorText(err, "Could not write the cover letter.");
      setLetterError(message);
      toast.error(message);
    } finally {
      setLoadingLetter(false);
    }
  };

  const fetchRecruiterMsg = async (target: Platform = platform, regenerate = false) => {
    setLoadingMsg(true);
    setMsgError(null);
    try {
      const msg = await generateRecruiterMessage(generationId, target, regenerate);
      setMessages((prev) => ({ ...prev, [target]: msg }));
    } catch (err) {
      const message = errorText(err, "Could not write the recruiter message.");
      setMsgError(message);
      toast.error(message);
    } finally {
      setLoadingMsg(false);
    }
  };

  const handleCopy = async (text: string) => {
    if (await copyText(text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error("Could not copy. Select the text and copy it yourself.");
    }
  };

  const choosePlatform = (target: Platform) => {
    setPlatform(target);
    setMsgError(null);
    if (!messages[target]) fetchRecruiterMsg(target);
  };

  return (
    <div className="space-y-4 rounded-xl border bg-card p-4 shadow-sm sm:p-5">
      {/* Header & Tabs */}
      <div className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold">Job outreach</h3>
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="h-3 w-3" />
              Checked against your resumes
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {jobTitle && company ? `For ${jobTitle} at ${company}` : "Written from your tailored draft"}
          </p>
        </div>

        <div className="flex items-center rounded-lg border bg-muted/30 p-1 text-xs" role="tablist" aria-label="Outreach type">
          <button
            role="tab"
            aria-selected={activeTab === "cover_letter"}
            onClick={() => setActiveTab("cover_letter")}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors",
              activeTab === "cover_letter" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <FileCheck2 className="h-3.5 w-3.5" />
            Cover letter
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "recruiter"}
            onClick={() => setActiveTab("recruiter")}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors",
              activeTab === "recruiter" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Recruiter message
          </button>
        </div>
      </div>

      {/* Cover letter */}
      {activeTab === "cover_letter" && (
        <div className="space-y-3">
          {loadingLetter ? (
            <div className="flex items-center justify-center gap-2 p-12 text-sm text-muted-foreground">
              <RefreshCw className="h-4 w-4 animate-spin text-primary" />
              Writing your cover letter…
            </div>
          ) : letterError && !coverLetter ? (
            <Failure message={letterError} onRetry={() => fetchCoverLetter()} />
          ) : !coverLetter ? (
            <div className="rounded-lg border border-dashed p-6 text-center sm:p-8">
              <FileCheck2 className="mx-auto h-8 w-8 text-muted-foreground/40" />
              <h4 className="mt-2 text-sm font-semibold">Cover letter</h4>
              <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
                Written from your tailored draft. Anything your resumes don&rsquo;t back up is listed for you to check.
              </p>
              <button
                onClick={() => fetchCoverLetter()}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground shadow hover:bg-primary/90"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Write cover letter
              </button>
            </div>
          ) : (
            <>
              {letterError && <Failure message={letterError} onRetry={() => fetchCoverLetter(true)} />}
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 truncate text-xs font-medium text-muted-foreground">
                  Subject: {coverLetter.subject}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => fetchCoverLetter(true)}
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  >
                    <RefreshCw className="h-3 w-3" />
                    Regenerate
                  </button>
                  <button
                    onClick={() => handleCopy(coverLetter.full_text)}
                    className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-xs font-medium shadow-sm hover:bg-muted"
                  >
                    {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied ? "Copied" : "Copy letter"}
                  </button>
                </div>
              </div>
              <Notes warnings={coverLetter.warnings} stale={coverLetter.stale} onRegenerate={() => fetchCoverLetter(true)} />
              <div className="whitespace-pre-wrap rounded-lg border bg-muted/20 p-4 text-sm leading-relaxed text-foreground/90">
                {coverLetter.full_text}
              </div>
            </>
          )}
        </div>
      )}

      {/* Recruiter message */}
      {activeTab === "recruiter" && (
        <div className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
              <span>Channel:</span>
              <button
                onClick={() => choosePlatform("linkedin")}
                aria-pressed={platform === "linkedin"}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
                  platform === "linkedin" ? "border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400" : "text-muted-foreground hover:bg-muted"
                )}
              >
                <Linkedin className="h-3 w-3" />
                LinkedIn
              </button>
              <button
                onClick={() => choosePlatform("email")}
                aria-pressed={platform === "email"}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
                  platform === "email" ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"
                )}
              >
                <Mail className="h-3 w-3" />
                Email
              </button>
            </div>
            {recruiterMsg && !loadingMsg && (
              <button
                onClick={() => fetchRecruiterMsg(platform, true)}
                className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground sm:self-auto"
              >
                <RefreshCw className="h-3 w-3" />
                Regenerate
              </button>
            )}
          </div>

          {loadingMsg ? (
            <div className="flex items-center justify-center gap-2 p-12 text-sm text-muted-foreground">
              <RefreshCw className="h-4 w-4 animate-spin text-primary" />
              Writing your message…
            </div>
          ) : msgError && !recruiterMsg ? (
            <Failure message={msgError} onRetry={() => fetchRecruiterMsg(platform)} />
          ) : !recruiterMsg ? (
            <div className="rounded-lg border border-dashed p-6 text-center sm:p-8">
              <Send className="mx-auto h-8 w-8 text-muted-foreground/40" />
              <h4 className="mt-2 text-sm font-semibold">Recruiter message</h4>
              <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
                A short note (under 150 words) with 2–3 real achievements that match the job&rsquo;s main challenges.
              </p>
              <button
                onClick={() => fetchRecruiterMsg(platform)}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground shadow hover:bg-primary/90"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Write message
              </button>
            </div>
          ) : (
            <>
              {msgError && <Failure message={msgError} onRetry={() => fetchRecruiterMsg(platform, true)} />}
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0 truncate text-xs font-medium text-muted-foreground">
                  Subject: {recruiterMsg.subject}
                </span>
                <button
                  onClick={() => handleCopy(recruiterMsg.message)}
                  className="inline-flex items-center gap-1.5 self-start rounded-lg border bg-background px-3 py-1.5 text-xs font-medium shadow-sm hover:bg-muted sm:self-auto"
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
                  {copied ? "Copied" : "Copy message"}
                </button>
              </div>
              <Notes
                warnings={recruiterMsg.warnings}
                stale={recruiterMsg.stale}
                onRegenerate={() => fetchRecruiterMsg(platform, true)}
              />
              <div className="whitespace-pre-wrap rounded-lg border bg-muted/20 p-4 text-sm leading-relaxed text-foreground/90">
                {recruiterMsg.message}
              </div>
              {recruiterMsg.highlight_points?.length > 0 && (
                <div className="rounded-lg border bg-muted/10 p-3">
                  <div className="mb-1.5 text-xs font-semibold text-muted-foreground">Key points used</div>
                  <ul className="space-y-1 text-xs text-muted-foreground">
                    {recruiterMsg.highlight_points.map((p, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="text-primary">•</span>
                        <span>{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
