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
  page?: number;
  score?: number;
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
  isStreaming?: boolean;
  error?: string;
}

export const quickActions = [
  {
    id: "chat",
    label: "Ask your documents",
    description: "Chat with the AI and get answers with page citations.",
    icon: "message" as const,
    href: "/chat",
  },
  {
    id: "documents",
    label: "Manage documents",
    description: "View, re-index or delete the files you uploaded.",
    icon: "settings" as const,
    href: "/collections",
  },
] as const;

export const suggestedQuestions = [
  "What documents are in my knowledge base?",
  "Summarize the key points from my uploaded files.",
  "What are the main topics covered?",
  "Find information about product requirements.",
];
