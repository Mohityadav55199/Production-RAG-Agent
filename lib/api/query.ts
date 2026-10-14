import { getApiBase, ApiError, authedFetch } from "@/lib/api/client";
import { normalizeSources } from "@/lib/api/normalize";
import type { QuerySource } from "@/lib/types";

export type AnswerStyle = "detailed" | "concise";

export interface StreamHandlers {
  onToken: (token: string) => void;
  onSources: (sources: QuerySource[]) => void;
  onDone: () => void;
  onError: (error: Error) => void;
  onConversation?: (conversationId: string) => void;
  onDiff?: (diff: string) => void;
}

export interface StreamQueryOptions extends StreamHandlers {
  query: string;
  collectionId?: string | null;
  conversationId?: string | null;
  answerStyle?: AnswerStyle;
  project?: string | null;
  documentId?: string | null;
  scopeKind?: "all" | "documents" | "projects";
  /** Images to ask about (already downscaled). Needs a Gemini key on the server. */
  images?: { mime: string; data: string }[];
  signal?: AbortSignal;
}

function parseSseChunk(chunk: string, handlers: StreamHandlers) {
  const lines = chunk.split("\n");
  for (const line of lines) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (!data || data === "[DONE]") {
      handlers.onDone();
      return;
    }

    try {
      const parsed = JSON.parse(data) as Record<string, unknown>;
      const type = String(parsed.type ?? parsed.event ?? "");

      if (type === "sources" || parsed.sources) {
        handlers.onSources(normalizeSources(parsed.sources ?? parsed.data));
        continue;
      }

      if (type === "diff") {
        handlers.onDiff?.(String(parsed.diff ?? ""));
        continue;
      }

      if (type === "done") {
        if (parsed.conversation_id) {
          handlers.onConversation?.(String(parsed.conversation_id));
        }
        continue;
      }

      if (type === "thinking") continue;

      if (type === "error") {
        handlers.onError(
          new Error(String(parsed.message ?? parsed.content ?? "Stream error"))
        );
        return;
      }

      const token = String(
        parsed.content ??
          parsed.token ??
          parsed.text ??
          parsed.delta ??
          (type === "token" ? parsed.data : "") ??
          ""
      );
      if (token) handlers.onToken(token);
    } catch {
      if (data) handlers.onToken(data);
    }
  }
}

/** POST a JSON body and dispatch the Server-Sent Events response to handlers. */
export async function streamSse(
  path: string,
  body: unknown,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const apiBase = getApiBase();
  const res = await authedFetch(`${apiBase}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
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
        message = json.detail
          .map((d: { msg?: string }) => d?.msg ?? String(d))
          .join(", ");
      }
    } catch {
      // plain text error
    }
    throw new ApiError(res.status, message);
  }

  const contentType = res.headers.get("content-type") ?? "";

  if (!contentType.includes("text/event-stream")) {
    const json = (await res.json()) as Record<string, unknown>;
    if (json.sources) {
      handlers.onSources(normalizeSources(json.sources));
    }
    const answer = String(json.answer ?? json.response ?? json.content ?? "");
    if (answer) handlers.onToken(answer);
    handlers.onDone();
    return;
  }

  if (!res.body) throw new ApiError(500, "No response stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) parseSseChunk(part, handlers);
  }

  if (buffer.trim()) parseSseChunk(buffer, handlers);
  handlers.onDone();
}

export async function streamQuery(options: StreamQueryOptions): Promise<void> {
  const detailed = (options.answerStyle ?? "detailed") === "detailed";
  return streamSse(
    "/query",
    {
      query: options.query,
      collection_id: options.collectionId ?? undefined,
      conversation_id: options.conversationId ?? undefined,
      answer_style: options.answerStyle ?? "detailed",
      top_k: detailed ? 12 : 5,
      scope_kind: options.scopeKind ?? "all",
      images: options.images?.length ? options.images : undefined,
      project: options.project ?? undefined,
      document_id: options.documentId ?? undefined,
      stream: true,
    },
    options,
    options.signal
  );
}
