export type DocumentStatus = "indexed" | "processing" | "failed" | "already_exists";

export interface Document {
  id: string;
  name: string;
  type: string;
  size: number;
  chunks: number;
  status: DocumentStatus;
  uploadedAt: Date;
  collectionId?: string;
  error?: string;
  /** Set when the document is a picture: show it from GET /assets/{id}?size=thumb */
  previewAssetId?: string;
}

export interface DashboardStats {
  totalDocuments: number;
  totalChunks: number;
  storageUsed: number;
  storageLimit: number;
}

export interface Collection {
  id: string;
  name: string;
  documentCount: number;
  createdAt: Date;
}

export interface QuerySource {
  documentId?: string;
  documentName?: string;
  chunkText?: string;
  fullText?: string;
  page?: number;
  chunkIndex?: number;
  score?: number;
  /** Stored pictures for this source's page (figures, or the image itself): GET /assets/{id} */
  images?: string[];
}

export interface HealthInfo {
  status: string;
  gemini: string;
  groq?: string;
  qdrant: string;
  postgres: string;
  backend: string;
  environment: string;
  version?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: QuerySource[];
  /** Images the user attached to this question (local previews only; never stored). */
  attachments?: { id: string; name: string; previewUrl: string }[];
  isStreaming?: boolean;
  error?: string;
  /** Active fallback model notification if primary LLM encountered rate limits. */
  fallbackNotice?: { model: string; provider?: string; message: string };
  /** The user's thumbs up/down on this answer. */
  rating?: "up" | "down";
}


export const suggestedQuestions = [
  "What documents are in my knowledge base?",
  "Summarize the key points from my uploaded files.",
  "What are the main topics covered?",
  "Find information about product requirements.",
];
