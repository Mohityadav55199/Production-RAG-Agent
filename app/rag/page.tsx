import { AppShell } from "@/components/layout/app-shell";
import { RagWorkspace } from "@/components/rag/rag-workspace";

export default function RagPage() {
  return (
    <AppShell activePath="/rag">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Chat with your documents</h1>
        <p className="mt-1 text-muted-foreground">
          Upload PDFs, Word, PowerPoint, Excel, CSV or text files, ask questions in plain English, and get
          answers grounded in your files, with the source and page for every claim
        </p>
      </div>
      <RagWorkspace />
    </AppShell>
  );
}
