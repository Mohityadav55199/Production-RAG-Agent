import { apiFetch } from "@/lib/api/client";

export type AnswerRating = "up" | "down";

export async function submitFeedback(input: {
  rating: AnswerRating;
  question: string;
  answer: string;
  conversationId?: string | null;
  citedFiles?: string[];
  comment?: string;
}): Promise<void> {
  await apiFetch<unknown>("/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rating: input.rating,
      question: input.question,
      answer: input.answer.slice(0, 20000),
      conversation_id: input.conversationId ?? null,
      cited_files: input.citedFiles ?? [],
      comment: input.comment || null,
    }),
  });
}
