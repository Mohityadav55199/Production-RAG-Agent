"use client";

import { useState } from "react";
import {
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
import {
  generateCoverLetter,
  generateRecruiterMessage,
  type CoverLetterResult,
  type RecruiterMessageResult,
} from "@/lib/api/resume";
import { cn } from "@/lib/utils";

interface OutreachPanelProps {
  generationId: string;
  company?: string;
  jobTitle?: string;
}

export function OutreachPanel({ generationId, company, jobTitle }: OutreachPanelProps) {
  const [activeTab, setActiveTab] = useState<"cover_letter" | "recruiter">("cover_letter");
  const [platform, setPlatform] = useState<"linkedin" | "email">("linkedin");

  const [coverLetter, setCoverLetter] = useState<CoverLetterResult | null>(null);
  const [recruiterMsg, setRecruiterMsg] = useState<RecruiterMessageResult | null>(null);

  const [loadingLetter, setLoadingLetter] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState(false);
  const [copied, setCopied] = useState(false);

  const fetchCoverLetter = async () => {
    setLoadingLetter(true);
    try {
      const res = await generateCoverLetter(generationId);
      setCoverLetter(res);
    } catch (err) {
      console.error("Cover letter generation failed", err);
    } finally {
      setLoadingLetter(false);
    }
  };

  const fetchRecruiterMsg = async (targetPlatform = platform) => {
    setLoadingMsg(true);
    try {
      const res = await generateRecruiterMessage(generationId, targetPlatform);
      setRecruiterMsg(res);
    } catch (err) {
      console.error("Recruiter message generation failed", err);
    } finally {
      setLoadingMsg(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
      {/* Header & Tabs */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-base">Grounded Job Outreach</h3>
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-500">
              <ShieldCheck className="h-3 w-3" />
              100% Grounded
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {jobTitle && company ? `Tailored for ${jobTitle} at ${company}` : "Grounded in your library evidence"}
          </p>
        </div>

        <div className="flex items-center rounded-lg border bg-muted/30 p-1 text-xs">
          <button
            onClick={() => {
              setActiveTab("cover_letter");
              if (!coverLetter && !loadingLetter) fetchCoverLetter();
            }}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors",
              activeTab === "cover_letter"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <FileCheck2 className="h-3.5 w-3.5" />
            Cover Letter
          </button>
          <button
            onClick={() => {
              setActiveTab("recruiter");
              if (!recruiterMsg && !loadingMsg) fetchRecruiterMsg();
            }}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors",
              activeTab === "recruiter"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Recruiter Message
          </button>
        </div>
      </div>

      {/* Tab 1: Cover Letter */}
      {activeTab === "cover_letter" && (
        <div className="space-y-4">
          {!coverLetter && !loadingLetter ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <FileCheck2 className="mx-auto h-8 w-8 text-muted-foreground/40" />
              <h4 className="mt-2 text-sm font-semibold">Generate Grounded Cover Letter</h4>
              <p className="mt-1 text-xs text-muted-foreground max-w-md mx-auto">
                Synthesizes your verified experience and projects into an authentic, compelling cover letter with zero fabricated claims.
              </p>
              <button
                onClick={fetchCoverLetter}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground shadow hover:bg-primary/90"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Generate Cover Letter
              </button>
            </div>
          ) : loadingLetter ? (
            <div className="flex items-center justify-center p-12 text-sm text-muted-foreground gap-2">
              <RefreshCw className="h-4 w-4 animate-spin text-primary" />
              Drafting grounded cover letter using your library...
            </div>
          ) : (
            coverLetter && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-xs text-muted-foreground font-medium truncate">
                    Subject: {coverLetter.subject}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={fetchCoverLetter}
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
                      {copied ? "Copied" : "Copy Letter"}
                    </button>
                  </div>
                </div>

                <div className="rounded-lg border bg-muted/20 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap text-foreground/90 select-all">
                  {coverLetter.full_text}
                </div>

                {coverLetter.warnings?.length > 0 && (
                  <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-500">
                    {coverLetter.warnings.map((w, i) => (
                      <div key={i}>• {w}</div>
                    ))}
                  </div>
                )}
              </div>
            )
          )}
        </div>
      )}

      {/* Tab 2: Recruiter Outreach Message */}
      {activeTab === "recruiter" && (
        <div className="space-y-4">
          {/* Platform Toggle */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-medium">
              <span>Channel:</span>
              <button
                onClick={() => {
                  setPlatform("linkedin");
                  fetchRecruiterMsg("linkedin");
                }}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium border",
                  platform === "linkedin"
                    ? "border-blue-500/40 bg-blue-500/10 text-blue-500"
                    : "text-muted-foreground hover:bg-muted"
                )}
              >
                <Linkedin className="h-3 w-3" />
                LinkedIn InMail
              </button>
              <button
                onClick={() => {
                  setPlatform("email");
                  fetchRecruiterMsg("email");
                }}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium border",
                  platform === "email"
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted"
                )}
              >
                <Mail className="h-3 w-3" />
                Direct Email
              </button>
            </div>

            {recruiterMsg && (
              <button
                onClick={() => fetchRecruiterMsg()}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <RefreshCw className="h-3 w-3" />
                Regenerate
              </button>
            )}
          </div>

          {!recruiterMsg && !loadingMsg ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <Send className="mx-auto h-8 w-8 text-muted-foreground/40" />
              <h4 className="mt-2 text-sm font-semibold">Generate Cold Outreach Message</h4>
              <p className="mt-1 text-xs text-muted-foreground max-w-md mx-auto">
                Punchy, concise note (under 150 words) highlighting 2-3 genuine achievements matching the job&rsquo;s core challenges.
              </p>
              <button
                onClick={() => fetchRecruiterMsg()}
                className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-xs font-medium text-primary-foreground shadow hover:bg-primary/90"
              >
                <Sparkles className="h-3.5 w-3.5" />
                Generate Recruiter Note
              </button>
            </div>
          ) : loadingMsg ? (
            <div className="flex items-center justify-center p-12 text-sm text-muted-foreground gap-2">
              <RefreshCw className="h-4 w-4 animate-spin text-primary" />
              Crafting concise recruiter message...
            </div>
          ) : (
            recruiterMsg && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground truncate">
                    Subject: {recruiterMsg.subject}
                  </span>
                  <button
                    onClick={() => handleCopy(recruiterMsg.message)}
                    className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-xs font-medium shadow-sm hover:bg-muted"
                  >
                    {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied ? "Copied" : "Copy Note"}
                  </button>
                </div>

                <div className="rounded-lg border bg-muted/20 p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap text-foreground/90 select-all">
                  {recruiterMsg.message}
                </div>

                {recruiterMsg.highlight_points?.length > 0 && (
                  <div className="rounded-lg border bg-muted/10 p-3">
                    <div className="text-xs font-semibold text-muted-foreground mb-1.5">Grounded Key Points:</div>
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
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
