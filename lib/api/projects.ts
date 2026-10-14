import { apiFetch } from "@/lib/api/client";

export interface ProjectImportResult {
  project_name: string;
  files_queued: number;
  files_skipped: number;
  truncated: boolean;
  message: string;
}

export function importGithubProject(url: string): Promise<ProjectImportResult> {
  return apiFetch<ProjectImportResult>("/projects/github", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
    timeout: 180000, // downloading a repo can take a while
  });
}

export function importZipProject(file: File): Promise<ProjectImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<ProjectImportResult>("/projects/zip", {
    method: "POST",
    body: formData,
    timeout: 300000,
  });
}

export interface ProjectProgress {
  name: string;
  total: number;
  indexed: number;
  processing: number;
  failed: number;
  first_error: string | null;
}

export async function listProjects(): Promise<ProjectProgress[]> {
  const data = await apiFetch<{ projects: ProjectProgress[] }>("/projects");
  return data.projects;
}

export function deleteProject(name: string): Promise<void> {
  return apiFetch<void>(`/projects/${encodeURIComponent(name)}`, { method: "DELETE", timeout: 120000 });
}
