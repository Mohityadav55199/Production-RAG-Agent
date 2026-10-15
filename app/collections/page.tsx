import { AppShell } from "@/components/layout/app-shell";
import { CollectionsManager } from "@/components/collections/collections-manager";
import { PageHeader } from "@/components/layout/page-header";

export default function CollectionsPage() {
  return (
    <AppShell activePath="/collections">
      <PageHeader title="Collections" description="Create and manage document collections" />

      <CollectionsManager />
    </AppShell>
  );
}
