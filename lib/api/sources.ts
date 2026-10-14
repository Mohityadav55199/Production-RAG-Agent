import { apiFetch } from "@/lib/api/client";
import { streamSse, type StreamHandlers } from "@/lib/api/query";

export interface KnowledgeSources {
  projects: { name: string; file_count: number }[];
  documents: { id: string; filename: string }[];
}

export function getSources(): Promise<KnowledgeSources> {
  return apiFetch<KnowledgeSources>("/projects/sources");
}

/**
 * A scope or compare side, encoded as a string for <select> values:
 * "all", "project:<name>" or "document:<id>".
 */
export type SourceKey = string;

export function parseSourceKey(key: SourceKey): {
  project: string | null;
  documentId: string | null;
} {
  if (key.startsWith("project:")) return { project: key.slice(8), documentId: null };
  if (key.startsWith("document:")) return { project: null, documentId: key.slice(9) };
  return { project: null, documentId: null };
}

export type CompareSide =
  | { type: "text"; content: string; label?: string }
  | { type: "project"; project: string }
  | { type: "document"; document_id: string };

export function streamCompare(
  body: { left: CompareSide; right: CompareSide; focus?: string },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  return streamSse("/compare", body, handlers, signal);
}
