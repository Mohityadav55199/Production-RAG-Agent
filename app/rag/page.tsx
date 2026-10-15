import { AppShell } from "@/components/layout/app-shell";
import { RagWorkspace } from "@/components/rag/rag-workspace";
import { PageHeader } from "@/components/layout/page-header";

export default function RagPage() {
  return (
    <AppShell activePath="/rag">
      <RagWorkspace header={<PageHeader className="mb-0" title="Chat with your documents" description="Ask questions about your files and get answers with the source and page." />} />
    </AppShell>
  );
}
