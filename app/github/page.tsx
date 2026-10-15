import { AppShell } from "@/components/layout/app-shell";
import { GithubWorkspace } from "@/components/github/github-workspace";
import { PageHeader } from "@/components/layout/page-header";

export default function GithubPage() {
  return (
    <AppShell activePath="/github">
      <GithubWorkspace header={<PageHeader className="mb-0" title="GitHub" description="Import a repository or project zip and study the code in depth" />} />
    </AppShell>
  );
}
