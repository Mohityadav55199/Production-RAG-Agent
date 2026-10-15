"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowUp,
  Check,
  Copy,
  Loader2,
  Plus,
  RotateCcw,
  Square,
  SquarePen,
  ThumbsDown,
  ThumbsUp,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import {
  MAX_CHAT_IMAGES,
  imageFilesFrom,
  prepareImage,
  releaseImages,
  type AttachedImage,
} from "@/lib/api/images";
import { submitFeedback, type AnswerRating } from "@/lib/api/feedback";
import { streamQuery, type AnswerStyle } from "@/lib/api/query";
import { parseSourceKey } from "@/lib/api/sources";
import { SourceSelect, useKnowledgeSources } from "@/components/chat/source-select";
import { CitationChips } from "@/components/chat/citation-chips";
import { useApp } from "@/lib/context/app-context";
import { suggestedQuestions, type ChatMessage } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ImageLightbox } from "@/components/ui/image-lightbox";
import { SafeMarkdown } from "@/components/ui/safe-markdown";
import { cn } from "@/lib/utils";

function createId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif";

interface ChatInterfaceProps {
  /** "documents" = uploaded files only, "projects" = imported code projects only. */
  mode: "documents" | "projects";
}

export function ChatInterface({ mode }: ChatInterfaceProps) {
  const codeMode = mode === "projects";
  const { activeCollectionId } = useApp();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastQuery, setLastQuery] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [scope, setScope] = useState("all");
  const [answerStyle, setAnswerStyle] = useState<AnswerStyle>("detailed");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const { sources: knowledgeSources } = useKnowledgeSources();
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Images attached to the next question
  const [attachments, setAttachments] = useState<AttachedImage[]>([]);
  const [preparing, setPreparing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [lightbox, setLightbox] = useState<{ id: string; title: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastRequestRef = useRef<{ images: AttachedImage[] } | null>(null);

  const defaultImageQuestion = codeMode
    ? "Explain what this screenshot shows and how it relates to the code."
    : "Describe this image and explain anything in it that relates to my documents.";

  const starterQuestions = codeMode
    ? [
        "Explain this project: what it does, its architecture and main components.",
        "Walk me through the folder structure and what each part is responsible for.",
        "How does a request flow through the code, step by step?",
        "What are the main dependencies and how do I run this project?",
        "What bugs, risks or improvements do you see in this code?",
      ]
    : suggestedQuestions;

  // Switching project/document starts a fresh conversation (the old history is about something else)
  useEffect(() => {
    setConversationId(null);
  }, [scope]);

  const addImages = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return;
      const room = MAX_CHAT_IMAGES - attachments.length;
      if (room <= 0) {
        toast.error(`You can attach up to ${MAX_CHAT_IMAGES} images to one question.`);
        return;
      }
      if (files.length > room) {
        toast.info(`Only ${MAX_CHAT_IMAGES} images fit in one question. The extra ones were skipped.`);
      }
      setPreparing(true);
      const results = await Promise.allSettled(files.slice(0, room).map(prepareImage));
      const ready: AttachedImage[] = [];
      for (const result of results) {
        if (result.status === "fulfilled") ready.push(result.value);
        else toast.error(result.reason instanceof Error ? result.reason.message : "Could not add that image.");
      }
      setAttachments((prev) => [...prev, ...ready].slice(0, MAX_CHAT_IMAGES));
      setPreparing(false);
    },
    [attachments.length]
  );

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      releaseImages(prev.filter((image) => image.id === id));
      return prev.filter((image) => image.id !== id);
    });
  };

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

  const startNewChat = () => {
    abortRef.current?.abort();
    releaseImages(attachments);
    messages.forEach((message) => message.attachments && releaseImages(message.attachments));
    setAttachments([]);
    setMessages([]);
    setConversationId(null);
    setLastQuery(null);
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    toast.success("Copied to clipboard");
    setTimeout(() => setCopiedId(null), 2000);
  };

  useEffect(() => {
    // Scroll only the conversation, never the page around it
    const box = scrollRef.current;
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const sendQuery = useCallback(
    async (query: string, retry = false) => {
      // A retry re-sends the images of the failed question; a new question sends what is attached now
      const images = retry ? (lastRequestRef.current?.images ?? []) : attachments;
      const text = query.trim() || (images.length > 0 ? defaultImageQuestion : "");
      if (!text || isStreaming || preparing) return;

      setLastQuery(text);
      lastRequestRef.current = { images };
      const userMessage: ChatMessage = {
        id: createId(),
        role: "user",
        content: text,
        attachments: images.map(({ id, name, previewUrl }) => ({ id, name, previewUrl })),
      };

      const assistantId = createId();
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        isStreaming: true,
      };

      if (retry) {
        setMessages((prev) => {
          const next = [...prev];
          if (next[next.length - 1]?.role === "assistant") next.pop();
          return [...next, assistantMessage];
        });
      } else {
        setMessages((prev) => [...prev, userMessage, assistantMessage]);
      }

      setInput("");
      if (!retry) setAttachments([]);       // previews live on in the message, so they are not released here
      setIsStreaming(true);
      abortRef.current = new AbortController();

      try {
        const { project, documentId } = parseSourceKey(scope);
        await streamQuery({
          query: text,
          images: images.map(({ mime, data }) => ({ mime, data })),
          collectionId: activeCollectionId,
          conversationId,
          answerStyle,
          scopeKind: mode,
          project,
          documentId,
          signal: abortRef.current.signal,
          onConversation: setConversationId,
          onToken: (token) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, content: msg.content + token }
                  : msg
              )
            );
          },
          onSources: (sources) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId ? { ...msg, sources } : msg
              )
            );
          },
          onModelSwitched: (fallbackNotice) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId ? { ...msg, fallbackNotice } : msg
              )
            );
            toast.info(`Primary provider rate-limited: Switched to ${fallbackNotice.model}`);
          },
          onDone: () => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? { ...msg, isStreaming: false }
                  : msg
              )
            );
          },
          onError: (error) => {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantId
                  ? {
                      ...msg,
                      isStreaming: false,
                      error: error.message,
                      content: msg.content || "Something went wrong.",
                    }
                  : msg
              )
            );
          },
        });
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        const message =
          err instanceof Error ? err.message : "Failed to get response";
        toast.error(message);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantId
              ? { ...msg, isStreaming: false, error: message }
              : msg
          )
        );
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [activeCollectionId, isStreaming, preparing, attachments, defaultImageQuestion, scope, answerStyle, conversationId, mode]
  );

  const rateAnswer = async (message: ChatMessage, rating: AnswerRating) => {
    if (message.rating === rating) return;
    const index = messages.findIndex((m) => m.id === message.id);
    const question = [...messages.slice(0, index)].reverse().find((m) => m.role === "user")?.content;
    if (!question) return;
    setMessages((prev) => prev.map((m) => (m.id === message.id ? { ...m, rating } : m)));
    try {
      await submitFeedback({
        rating,
        question,
        answer: message.content,
        conversationId: conversationId,
        citedFiles: [...new Set((message.sources ?? []).map((s) => s.documentName).filter(Boolean))] as string[],
      });
      toast.success("Thanks for the feedback");
    } catch (err) {
      setMessages((prev) => prev.map((m) => (m.id === message.id ? { ...m, rating: undefined } : m)));
      toast.error(err instanceof Error ? err.message : "Could not send feedback");
    }
  };

  const stopGeneration = () => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setMessages((prev) =>
      prev.map((msg) =>
        msg.isStreaming ? { ...msg, isStreaming: false } : msg
      )
    );
  };

  const canSend = (input.trim().length > 0 || attachments.length > 0) && !preparing;

  return (
    // Fills the screen below the app and page headers, so the input is visible without scrolling
    <div className="flex h-[calc(100dvh-10.75rem)] min-h-[24rem] flex-col sm:h-[calc(100dvh-9.5rem)]">
      <div
        className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card"
        onDragOver={(e) => {
          if (hasFiles(e) && !isStreaming) {
            e.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={(e) => {
          setDragging(false);
          const files = imageFilesFrom(e.dataTransfer);
          if (files.length > 0 && !isStreaming) {
            e.preventDefault();
            void addImages(files);
          }
        }}
      >
        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-primary/10 text-sm font-medium text-primary">
            Drop images here to ask about them
          </div>
        )}

        {/* Slim top bar: what to search, answer style, new chat */}
        <div className="flex items-center gap-2 border-b border-border/60 px-3 py-2">
          <SourceSelect
            value={scope}
            onChange={setScope}
            sources={knowledgeSources}
            includeAll
            allLabel={codeMode ? "All imported projects" : "All my documents"}
            kind={mode}
            disabled={isStreaming}
            className="h-8 max-w-[60%] flex-1 rounded-full border-transparent bg-muted/60 text-xs shadow-none hover:bg-muted sm:max-w-xs"
          />
          <div className="ml-auto inline-flex shrink-0 rounded-full bg-muted/60 p-0.5" role="group" aria-label="Answer style">
            {(["detailed", "concise"] as const).map((style) => (
              <button
                key={style}
                type="button"
                onClick={() => setAnswerStyle(style)}
                aria-pressed={answerStyle === style}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                  answerStyle === style ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {style}
              </button>
            ))}
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="size-8 shrink-0 rounded-full"
            onClick={startNewChat}
            disabled={messages.length === 0}
            aria-label="New chat"
            title="New chat"
          >
            <SquarePen className="size-4" />
          </Button>
        </div>

        {/* Conversation */}
        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
            {messages.length === 0 ? (
              <div className="flex min-h-[40vh] flex-col items-center justify-center gap-6 text-center">
                <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
                  {codeMode ? "What do you want to know about your code?" : "What would you like to know?"}
                </h2>
                <div className="grid w-full max-w-2xl gap-2 sm:grid-cols-2">
                  {starterQuestions.map((question) => (
                    <button
                      key={question}
                      type="button"
                      disabled={isStreaming}
                      onClick={() => sendQuery(question)}
                      className="rounded-xl border bg-background px-3.5 py-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                    >
                      {question}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-8">
                {messages.map((message) =>
                  message.role === "user" ? (
                    <div key={message.id} className="flex justify-end">
                      <div className="max-w-[85%] space-y-2">
                        {message.attachments && message.attachments.length > 0 && (
                          <div className="flex flex-wrap justify-end gap-2">
                            {message.attachments.map((image) => (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                key={image.id}
                                src={image.previewUrl}
                                alt={image.name}
                                className="max-h-40 max-w-full rounded-2xl border object-cover"
                              />
                            ))}
                          </div>
                        )}
                        {message.content && (
                          <div className="whitespace-pre-wrap break-words rounded-3xl bg-muted px-4 py-2.5 text-[15px] leading-relaxed">
                            {message.content}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div key={message.id} className="group">
                      {message.fallbackNotice && (
                        <div className="mb-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-800 dark:text-amber-200">
                          <Zap className="size-3.5 shrink-0 text-amber-500" />
                          <span>
                            Answered by <strong>{message.fallbackNotice.model}</strong> because the main model is busy.
                          </span>
                        </div>
                      )}
                      <div className="prose prose-sm max-w-none text-[15px] leading-relaxed dark:prose-invert sm:prose-base">
                        {message.content ? (
                          <SafeMarkdown>{message.content}</SafeMarkdown>
                        ) : message.isStreaming ? (
                          <span className="inline-flex items-center gap-1 text-muted-foreground" role="status" aria-label="Thinking">
                            <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.2s]" />
                            <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.1s]" />
                            <span className="size-1.5 animate-bounce rounded-full bg-current" />
                          </span>
                        ) : null}
                        {message.isStreaming && message.content && (
                          <span className="ml-0.5 inline-block animate-pulse">▍</span>
                        )}
                      </div>

                      {message.error && (
                        <div className="mt-2 flex items-center gap-2 text-sm text-destructive">
                          <AlertCircle className="size-4" />
                          {message.error}
                        </div>
                      )}

                      {message.sources && message.sources.length > 0 && <CitationChips sources={message.sources} />}

                      {!message.isStreaming && (message.content || message.error) && (
                        <div className="mt-1.5 flex items-center gap-0.5 text-muted-foreground">
                          {message.content && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7 rounded-lg hover:text-foreground"
                              onClick={() => copyToClipboard(message.content, message.id)}
                              aria-label="Copy answer"
                              title="Copy"
                            >
                              {copiedId === message.id ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
                            </Button>
                          )}
                          {!message.error && message.content &&
                            (["up", "down"] as const).map((value) => (
                              <Button
                                key={value}
                                variant="ghost"
                                size="icon"
                                aria-label={value === "up" ? "Good answer" : "Bad answer"}
                                title={value === "up" ? "Good answer" : "Bad answer"}
                                aria-pressed={message.rating === value}
                                className={cn("size-7 rounded-lg hover:text-foreground", message.rating === value && "text-foreground")}
                                onClick={() => rateAnswer(message, value)}
                              >
                                {value === "up" ? (
                                  <ThumbsUp className={cn("size-3.5", message.rating === value && "fill-current")} />
                                ) : (
                                  <ThumbsDown className={cn("size-3.5", message.rating === value && "fill-current")} />
                                )}
                              </Button>
                            ))}
                          {message.error && lastQuery && (
                            <Button variant="ghost" size="sm" className="h-7 gap-1 rounded-lg px-2 text-xs" onClick={() => sendQuery(lastQuery, true)}>
                              <RotateCcw className="size-3.5" />
                              Retry
                            </Button>
                          )}
                        </div>
                      )}
                    </div>
                  )
                )}
                <div ref={bottomRef} />
              </div>
            )}
          </div>
        </div>

        {/* Composer */}
        <div className="px-3 pb-3 pt-1 sm:px-4">
          <form
            className="mx-auto w-full max-w-3xl rounded-3xl border bg-background shadow-sm focus-within:border-ring/60 focus-within:shadow-md"
            onSubmit={(e) => {
              e.preventDefault();
              sendQuery(input);
            }}
          >
            {(attachments.length > 0 || preparing) && (
              <div className="flex flex-wrap items-center gap-2 px-3 pt-3" aria-label="Attached images">
                {attachments.map((image) => (
                  <div key={image.id} className="relative">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={image.previewUrl} alt={image.name} className="size-14 rounded-xl border object-cover" />
                    <button
                      type="button"
                      onClick={() => removeAttachment(image.id)}
                      aria-label={`Remove ${image.name}`}
                      className="absolute -right-1.5 -top-1.5 rounded-full border bg-background p-0.5 shadow-sm hover:bg-muted"
                    >
                      <X className="size-3" />
                    </button>
                  </div>
                ))}
                {preparing && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Preparing image" />}
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={IMAGE_ACCEPT}
              multiple
              className="hidden"
              data-testid="chat-image-input"
              onChange={(e) => {
                void addImages(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            <div className="flex items-end gap-1.5 p-2">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-9 shrink-0 rounded-full text-muted-foreground"
                onClick={() => fileInputRef.current?.click()}
                disabled={isStreaming || preparing || attachments.length >= MAX_CHAT_IMAGES}
                aria-label="Attach an image"
                title="Attach an image (you can also paste or drop one)"
              >
                <Plus className="size-5" />
              </Button>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onPaste={(e) => {
                  const files = imageFilesFrom(e.clipboardData);
                  if (files.length > 0) {
                    e.preventDefault();
                    void addImages(files);
                  }
                }}
                placeholder={codeMode ? "Ask about the code" : "Ask anything about your documents"}
                aria-label="Message"
                className="max-h-48 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] outline-none [field-sizing:content] placeholder:text-muted-foreground disabled:opacity-60"
                rows={1}
                disabled={isStreaming}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendQuery(input);
                  }
                }}
              />
              {isStreaming ? (
                <Button type="button" size="icon" className="size-9 shrink-0 rounded-full" onClick={stopGeneration} aria-label="Stop">
                  <Square className="size-3.5 fill-current" />
                </Button>
              ) : (
                <Button type="submit" size="icon" className="size-9 shrink-0 rounded-full" disabled={!canSend} aria-label="Send">
                  <ArrowUp className="size-4" />
                </Button>
              )}
            </div>
          </form>
          <p className="mt-1.5 hidden text-center text-[11px] text-muted-foreground sm:block">
            Answers come from your {codeMode ? "projects" : "documents"} and cite their sources. Check anything important.
          </p>
        </div>
      </div>
      <ImageLightbox assetId={lightbox?.id ?? null} title={lightbox?.title} onClose={() => setLightbox(null)} />
    </div>
  );
}
