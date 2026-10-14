import { apiFetch, ApiError, authedFetch, getApiBase } from "@/lib/api/client";

// ── Types ────────────────────────────────────────────────────────────────────

export interface ResumeSummary {
  id: string;
  label: string;
  filename: string | null;
  file_type: string;
  index_status: "pending" | "ready" | "failed";
  item_count: number;
  created_at: string | null;
  name: string;
  counts: { experience: number; projects: number; skills: number; education: number };
}

export interface ScoreComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  details: string;
  findings: string[];
}

export interface AtsReport {
  total: number;
  components: ScoreComponent[];
  matched: string[];
  missing_must: string[];
  missing_nice: string[];
  fixes: string[];
  pdf_checked: boolean;
  has_jd: boolean;
  pdf_compiled?: boolean;
}

export interface JdInfo {
  title: string;
  company: string;
  seniority: string;
  must_have: string[];
  nice_to_have: string[];
  responsibilities: string[];
}

export interface AtsCheckResult {
  filename: string;
  report: AtsReport;
  jd: JdInfo | null;
  pages: number | null;
  extracted_preview: string;
  disclaimer: string;
}

export interface TailorStep {
  type: "step";
  step: "analyze" | "retrieve" | "write" | "score" | "revise";
  status: "running" | "done";
  message: string;
  attempt?: number;
  score?: number;
  components?: { label: string; score: number }[];
}

export interface TailorResult {
  type: "result";
  generation_id: string;
  output_name: string;
  score: number;
  threshold: number;
  released: boolean;
  attempts: number;
  pdf_available: boolean;
  pdf_compiled: boolean;
  tex: string | null;
  report: AtsReport;
  warnings: string[];
  jd: JdInfo;
}

export interface GenerationSummary {
  id: string;
  output_name: string;
  job_title: string | null;
  company: string | null;
  ats_score: number;
  threshold: number;
  released: boolean;
  pdf_available: boolean;
  attempts: number;
  created_at: string | null;
}

// ── Library ──────────────────────────────────────────────────────────────────

export async function listResumes(): Promise<ResumeSummary[]> {
  const data = await apiFetch<{ resumes: ResumeSummary[] }>("/resume/library");
  return data.resumes;
}

export function addResume(input: { file?: File; text?: string; label?: string }): Promise<ResumeSummary> {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  if (input.text) form.append("text", input.text);
  if (input.label) form.append("label", input.label);
  return apiFetch<ResumeSummary>("/resume/library", { method: "POST", body: form, timeout: 120000 });
}

export function deleteResume(id: string): Promise<void> {
  return apiFetch<void>(`/resume/library/${id}`, { method: "DELETE" });
}

// ── Job description & ATS check ──────────────────────────────────────────────

export async function extractText(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const data = await apiFetch<{ text: string }>("/resume/extract-text", { method: "POST", body: form, timeout: 60000 });
  return data.text;
}

export function atsCheck(file: File, jdText?: string): Promise<AtsCheckResult> {
  const form = new FormData();
  form.append("file", file);
  if (jdText?.trim()) form.append("jd_text", jdText.trim());
  return apiFetch<AtsCheckResult>("/resume/ats-check", { method: "POST", body: form, timeout: 120000 });
}

// ── Tailoring (SSE) ──────────────────────────────────────────────────────────

export type TailorEvent = TailorStep | TailorResult | { type: "error"; message: string } | { type: "heartbeat" } | { type: "thinking" };

export async function streamTailor(
  body: { jd_text: string; output_name: string; resume_ids?: string[] },
  onEvent: (event: TailorEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await authedFetch(`${getApiBase()}/resume/tailor`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let message = text || res.statusText;
    try {
      const json = JSON.parse(text) as { detail?: unknown };
      if (typeof json.detail === "string") message = json.detail;
      else if (Array.isArray(json.detail)) {
        message = json.detail.map((d: { msg?: string }) => d?.msg ?? String(d)).join(", ");
      }
    } catch {
      // plain text
    }
    throw new ApiError(res.status, message);
  }
  if (!res.body) throw new ApiError(500, "No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handle = (chunk: string) => {
    for (const line of chunk.split("\n")) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      try {
        onEvent(JSON.parse(data) as TailorEvent);
      } catch {
        // ignore malformed frame
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    parts.forEach(handle);
  }
  if (buffer.trim()) handle(buffer);
}

// ── History & downloads ──────────────────────────────────────────────────────

export async function listGenerations(): Promise<GenerationSummary[]> {
  const data = await apiFetch<{ generations: GenerationSummary[] }>("/resume/generations");
  return data.generations;
}

export function deleteGeneration(id: string): Promise<void> {
  return apiFetch<void>(`/resume/generations/${id}`, { method: "DELETE" });
}

export function getGenerationTex(id: string): Promise<{ tex: string | null; report: AtsReport }> {
  return apiFetch(`/resume/generations/${id}`);
}

/** Download a released file. Goes through fetch so errors (e.g. gate not passed) can be shown. */
export async function downloadGenerationFile(id: string, kind: "pdf" | "tex", filename: string): Promise<void> {
  const res = await authedFetch(`${getApiBase()}/resume/generations/${id}/${kind}`);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const json = (await res.json()) as { detail?: string };
      if (json.detail) message = json.detail;
    } catch {
      // keep status text
    }
    throw new ApiError(res.status, message);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
