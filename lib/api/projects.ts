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
