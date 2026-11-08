import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { streamSse, type StreamHandlers } from "@/lib/api/query";

/** A fetch() response that delivers the given strings as separate network chunks. */
function sseResponse(chunks: string[], init: ResponseInit = {}): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" }, ...init });
}

const event = (payload: unknown) => `data: ${JSON.stringify(payload)}\n\n`;

function makeHandlers() {
  const calls = {
    tokens: [] as string[],
    sources: [] as unknown[],
    steps: [] as { step: string; label: string }[],
    conversations: [] as string[],
    errors: [] as Error[],
    done: 0,
  };
  const handlers: StreamHandlers = {
    onToken: (t) => calls.tokens.push(t),
    onSources: (s) => calls.sources.push(s),
    onStep: (s) => calls.steps.push(s),
    onConversation: (c) => calls.conversations.push(c),
    onError: (e) => calls.errors.push(e),
    onDone: () => {
      calls.done += 1;
    },
  };
  return { calls, handlers };
}

afterEach(() => vi.unstubAllGlobals());

describe("streamSse", () => {
  it("dispatches steps, sources, tokens and the conversation id in order", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse([
          event({ type: "thinking" }),
          event({ type: "step", step: "searching", label: "Searching your documents" }),
          event({ type: "sources", sources: [{ document_name: "a.md", chunk_text: "x", score: 0.9 }], retrieved_count: 1 }),
          event({ type: "step", step: "generating", label: "Writing the answer" }),
          event({ type: "chunk", content: "Hello" }),
          event({ type: "chunk", content: " world" }),
          event({ type: "done", conversation_id: "c-1", total_chars: 11 }),
          "data: [DONE]\n\n",
        ])
      )
    );
    const { calls, handlers } = makeHandlers();

    await streamSse("/query", { query: "hi" }, handlers);

    expect(calls.steps.map((s) => s.step)).toEqual(["searching", "generating"]);
    expect(calls.steps[0].label).toBe("Searching your documents");
    expect(calls.sources).toHaveLength(1);
    expect(calls.tokens.join("")).toBe("Hello world");
    expect(calls.conversations).toEqual(["c-1"]);
    expect(calls.errors).toEqual([]);
    expect(calls.done).toBeGreaterThan(0);
  });

  it("reassembles an event that arrives split across network chunks", async () => {
    const full = event({ type: "chunk", content: "split-token" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([full.slice(0, 12), full.slice(12)])));
    const { calls, handlers } = makeHandlers();

    await streamSse("/query", {}, handlers);

    expect(calls.tokens).toEqual(["split-token"]);
  });

  it("reports an error event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse([event({ type: "error", message: "Model unavailable" })]))
    );
    const { calls, handlers } = makeHandlers();

    await streamSse("/query", {}, handlers);

    expect(calls.errors.map((e) => e.message)).toEqual(["Model unavailable"]);
  });

  it("throws an ApiError with the server detail message for a failed request", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Daily limit reached" }), { status: 429 }))
    );
    const { handlers } = makeHandlers();

    const failure = await streamSse("/query", {}, handlers).catch((e: unknown) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).status).toBe(429);
    expect((failure as ApiError).message).toBe("Daily limit reached");
  });

  it("falls back to a plain JSON answer when the server does not stream", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ answer: "Plain answer", sources: [] }), {
          status: 200,
          headers: { "content-type": "application/json" },
        })
      )
    );
    const { calls, handlers } = makeHandlers();

    await streamSse("/query", {}, handlers);

    expect(calls.tokens).toEqual(["Plain answer"]);
    expect(calls.done).toBe(1);
  });
});
