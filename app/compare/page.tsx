import { AppShell } from "@/components/layout/app-shell";
import { ComparePanel } from "@/components/chat/compare-panel";
import { PageHeader } from "@/components/layout/page-header";

export default function ComparePage() {
  return (
    <AppShell activePath="/compare">
      <PageHeader title="Compare Code" description="Compare two solutions, files or repos, including DSA problems in C++, Java or Python" />
      <ComparePanel />
    </AppShell>
  );
}
