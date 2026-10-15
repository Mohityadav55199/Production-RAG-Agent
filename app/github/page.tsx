import { AppShell } from "@/components/layout/app-shell";
import { GithubWorkspace } from "@/components/github/github-workspace";
import { PageHeader } from "@/components/layout/page-header";

export default function GithubPage() {
  return (
    <AppShell activePath="/github">
      <PageHeader title="GitHub" description="Import a repository or project zip and study the code in depth" />
      <GithubWorkspace />
    </AppShell>
  );
}
