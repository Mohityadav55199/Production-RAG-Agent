import { AppShell } from "@/components/layout/app-shell";
import { ComparePanel } from "@/components/chat/compare-panel";

export default function ComparePage() {
  return (
    <AppShell activePath="/compare">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Compare Code</h1>
        <p className="mt-1 text-muted-foreground">
          Compare two solutions, files or repos, including DSA problems in C++, Java or Python
        </p>
      </div>
      <ComparePanel />
    </AppShell>
  );
}
