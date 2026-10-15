import { AppShell } from "@/components/layout/app-shell";
import { DocumentsList } from "@/components/documents/documents-list";
import { PageHeader } from "@/components/layout/page-header";

export default function DocumentsPage() {
  return (
    <AppShell activePath="/documents">
      <PageHeader title="Documents" description="View and manage all uploaded documents" />

      <DocumentsList />
    </AppShell>
  );
}
