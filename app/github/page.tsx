import { AppShell } from "@/components/layout/app-shell";
import { GithubWorkspace } from "@/components/github/github-workspace";

export default function GithubPage() {
  return (
    <AppShell activePath="/github">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">GitHub</h1>
        <p className="mt-1 text-muted-foreground">
          Import a repository or project zip and study the code in depth
        </p>
      </div>
      <GithubWorkspace />
    </AppShell>
  );
}
