"use client";

import { useRef, useState } from "react";
import { FileSearch, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";
import { atsCheck, type AtsCheckResult } from "@/lib/api/resume";
import { ScoreReport } from "@/components/resume/score-report";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function AtsCheckPanel() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AtsCheckResult | null>(null);

  const run = async () => {
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      setResult(await atsCheck(file, jd));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "ATS check failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Check the ATS score of any resume</CardTitle>
          <CardDescription>
            Upload a PDF or DOCX. We read its text the way an applicant tracking system does, then score parsing,
            format and, if you add a job description, keyword match.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx"
              className="hidden"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setResult(null);
              }}
            />
            <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={busy}>
              <Upload className="size-4" />
              {file ? "Change file" : "Choose PDF or DOCX"}
            </Button>
            {file && <span className="truncate text-sm text-muted-foreground">{file.name}</span>}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="ats-jd" className="text-sm font-medium">
              Job description <span className="font-normal text-muted-foreground">(optional, enables keyword match)</span>
            </label>
            <Textarea
              id="ats-jd"
              value={jd}
              onChange={(e) => setJd(e.target.value)}
              placeholder="Paste a job description to score keyword match…"
              className="min-h-[120px] text-sm"
              disabled={busy}
            />
          </div>

          <Button onClick={run} disabled={!file || busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <FileSearch className="size-4" />}
            {busy ? "Checking…" : "Check ATS score"}
          </Button>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              Result for {result.filename}
              {result.pages ? <span className="font-normal text-muted-foreground"> · {result.pages} page{result.pages === 1 ? "" : "s"}</span> : null}
            </CardTitle>
            <CardDescription>
              {result.report.has_jd
                ? `Scored against ${result.jd?.title || "the job description"}`
                : "Scored for format and parseability only. Add a job description for keyword match."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <ScoreReport report={result.report} />
            <details className="rounded-lg border">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium">What the ATS reads from your file</summary>
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap border-t bg-muted/30 p-3 text-xs leading-relaxed">
                {result.extracted_preview}
              </pre>
            </details>
            <p className="text-xs text-muted-foreground">{result.disclaimer}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
