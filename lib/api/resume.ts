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
  tex_available: boolean;
  pdf_compiled: boolean;
  tex: string | null;
  report: AtsReport;
  warnings: string[];
  jd: JdInfo;
}

export type TemplateName = "classic" | "compact" | "skills_first" | "student";

export type SectionName = "summary" | "skills" | "experience" | "projects" | "education" | "certifications" | "achievements";

export interface RenderOptions {
  template: TemplateName;
  font_pt: 10 | 11 | 12;
  margin_in: 0.5 | 0.6 | 0.75 | 1;
  font?: "serif" | "sans";
  /** Section order, e.g. copied from your own PDF; sections it leaves out follow in the template's order. */
  section_order?: SectionName[] | null;
  /** A saved layout; when it holds your own LaTeX template, the server renders inside it. */
  layout_id?: string | null;
  layout_name?: string | null;
  /** Set by the server from the saved layout; anything sent from here is ignored. */
  preamble?: string | null;
}

export interface SavedLayout {
  id: string;
  name: string;
  source: "saved" | "latex" | "pdf";
  has_template: boolean;
  options: RenderOptions;
  created_at: string | null;
  notes?: string[];
}

export function listLayouts(): Promise<SavedLayout[]> {
  return apiFetch<SavedLayout[]>("/resume/layouts");
}

export function saveLayout(name: string, options: RenderOptions): Promise<SavedLayout> {
  return apiFetch<SavedLayout>("/resume/layouts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, options: { ...options, preamble: null } }),
  });
}

/** Make a layout from your own resume: a .tex (its template), a .pdf (its look), or pasted LaTeX code. */
export function importLayout(file?: File | null, name = "", latexText?: string): Promise<SavedLayout> {
  const form = new FormData();
  if (file) form.append("file", file);
  if (latexText) form.append("latex_text", latexText);
  if (name) form.append("name", name);
  return apiFetch<SavedLayout>("/resume/layouts/import", { method: "POST", body: form, timeout: 120000 });
}

export function deleteLayout(id: string): Promise<void> {
  return apiFetch<void>(`/resume/layouts/${id}`, { method: "DELETE" });
}

export const DEFAULT_RENDER_OPTIONS: RenderOptions = { template: "classic", font_pt: 10, margin_in: 0.6, font: "serif" };

export interface ResumeProfile {
  name: string;
  email: string;
  phone: string;
  location: string;
  links: string[];
  summary: string;
  skills: Record<string, string[]>;
  experience: { company: string; title: string; location: string; dates: string; bullets: string[] }[];
  projects: { name: string; tech: string; link: string; bullets: string[] }[];
  education: { school: string; degree: string; dates: string; location: string; details: string }[];
  certifications: string[];
  achievements: string[];
}

/** Where a bullet came from, compared with the user's own library wording. */
export interface BulletInfo {
  text: string;
  status: "original" | "reworded" | "new";
  source: string | null;
  /** Job-description skills this bullet mentions (required = a must-have). */
  skills?: { term: string; required: boolean }[];
}

export interface AnnotatedRole {
  company: string;
  title: string;
  in_library: boolean;
  bullets: BulletInfo[];
  unused: string[];
}

export interface AnnotatedProject {
  name: string;
  in_library: boolean;
  bullets: BulletInfo[];
  unused: string[];
}

export interface Annotated {
  experience: AnnotatedRole[];
  projects: AnnotatedProject[];
  left_out_projects: { name: string; tech: string; bullets: string[] }[];
  new_skills: string[];
}

export interface GapReport {
  score: number;
  usable: { term: string; from: { kind: "experience" | "project"; item: string; bullet: string } | null }[];
  usable_score: number;
  lacking_must: string[];
  lacking_nice: string[];
  with_lacking_score: number;
}

export interface GenerationDetail extends GenerationSummary {
  report: AtsReport;
  details: { jd: JdInfo | null; warnings: string[]; compile_error: string };
  tex: string | null;
  below_threshold: boolean;
  editable: boolean;
  draft: ResumeProfile | null;
  ai_draft: ResumeProfile | null;
  options: RenderOptions;
  annotated: Annotated | null;
  gap: GapReport | null;
  outreach?: SavedOutreach;
  /** Your own resume(s) from the library, merged, for the side-by-side comparison. */
  library?: ResumeProfile | null;
  /** The job tracker entry that uses this run, if any. */
  job?: JobApplication | null;
}

/** Outreach saved with a run. `stale` = the draft was edited after it was written. */
export interface SavedOutreach {
  cover_letter: CoverLetterResult | null;
  recruiter: Partial<Record<"linkedin" | "email", RecruiterMessageResult>>;
}

export interface BulletOption {
  text: string;
  source: string | null;
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
  tex_available: boolean;
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
  body: { jd_text: string; output_name: string; resume_ids?: string[]; options?: RenderOptions },
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

export function getGeneration(id: string): Promise<GenerationDetail> {
  return apiFetch<GenerationDetail>(`/resume/generations/${id}`);
}

/** Re-render and re-score an edited draft; the server saves it and returns the refreshed detail. */
export function rescoreGeneration(id: string, draft: ResumeProfile, options: RenderOptions): Promise<GenerationDetail> {
  return apiFetch<GenerationDetail>(`/resume/generations/${id}/rescore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ draft, options }),
    timeout: 120000,
  });
}

/** Up to three alternatives for one bullet, each guaranteed to stay within the user's library. */
export async function regenerateBullet(
  id: string,
  body: { kind: "experience" | "project"; name: string; current?: string; already_used?: string[]; instruction?: string }
): Promise<BulletOption[]> {
  const data = await apiFetch<{ options: BulletOption[] }>(`/resume/generations/${id}/regenerate-bullet`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeout: 90000,
  });
  return data.options;
}

/** Download a compiled file. Goes through fetch so errors can be shown. */
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

/** Fetch a compiled PDF as a blob for live inline preview. */
export async function getGenerationPdfBlob(id: string): Promise<Blob> {
  const res = await authedFetch(`${getApiBase()}/resume/generations/${id}/pdf?inline=true`);
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
  return res.blob();
}

// ── Job Tracker & Outreach Types and APIs ────────────────────────────────────

export type JobStatus = "saved" | "applied" | "interviewing" | "offered" | "rejected" | "archived";

export interface JobApplication {
  id: string;
  company: string;
  job_title: string;
  job_url: string | null;
  location: string | null;
  salary: string | null;
  status: JobStatus;
  resume_generation_id: string | null;
  resume_version_name: string | null;
  ats_score: number | null;
  jd_text: string | null;
  notes: string | null;
  applied_date: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CoverLetterResult {
  subject: string;
  salutation: string;
  opening: string;
  body_paragraphs: string[];
  closing: string;
  sign_off: string;
  full_text: string;
  warnings: string[];
  stale?: boolean;
}

export interface RecruiterMessageResult {
  subject: string;
  preview: string;
  message: string;
  highlight_points: string[];
  platform: "linkedin" | "email";
  warnings: string[];
  stale?: boolean;
}

export async function listJobs(status?: string): Promise<JobApplication[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<JobApplication[]>(`/resume/jobs${query}`);
}

export function createJob(body: Partial<JobApplication> & { company: string; job_title: string }): Promise<JobApplication> {
  return apiFetch<JobApplication>("/resume/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getJob(id: string): Promise<JobApplication> {
  return apiFetch<JobApplication>(`/resume/jobs/${id}`);
}

export function updateJob(id: string, body: Partial<JobApplication>): Promise<JobApplication> {
  return apiFetch<JobApplication>(`/resume/jobs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteJob(id: string): Promise<void> {
  return apiFetch<void>(`/resume/jobs/${id}`, { method: "DELETE" });
}

/** The saved cover letter for a run, or a new one (always new when `regenerate`). */
export function generateCoverLetter(generationId: string, regenerate = false): Promise<CoverLetterResult> {
  return apiFetch<CoverLetterResult>(`/resume/generations/${generationId}/cover-letter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ regenerate }),
    timeout: 90000,
  });
}

export function generateRecruiterMessage(
  generationId: string,
  platform: "linkedin" | "email" = "linkedin",
  regenerate = false
): Promise<RecruiterMessageResult> {
  return apiFetch<RecruiterMessageResult>(`/resume/generations/${generationId}/recruiter-message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform, regenerate }),
    timeout: 90000,
  });
}


/** Create the tracker entry for this run, or move the existing one to "applied" (never backwards). */
export function markApplied(generationId: string): Promise<JobApplication> {
  return apiFetch<JobApplication>(`/resume/generations/${generationId}/apply`, { method: "POST" });
}
