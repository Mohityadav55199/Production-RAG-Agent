import { AppShell } from "@/components/layout/app-shell";
import { RagWorkspace } from "@/components/rag/rag-workspace";

export default function RagPage() {
  return (
    <AppShell activePath="/rag">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">RAG Agent</h1>
        <p className="mt-1 text-muted-foreground">
          Upload documents, then ask questions and get answers with citations
        </p>
      </div>
      <RagWorkspace />
    </AppShell>
  );
}
