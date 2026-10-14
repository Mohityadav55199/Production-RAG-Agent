"use client";

import { ChatInterface } from "@/components/chat/chat-interface";
import { ProjectImportCard } from "@/components/dashboard/project-import-card";
import { ProjectsOverview } from "@/components/github/projects-overview";
import { useProjects } from "@/lib/hooks/use-projects";

export function GithubWorkspace() {
  const { projects, loading, error, refetch, watch } = useProjects();

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <ProjectImportCard onImportStarted={watch} />
        <ProjectsOverview projects={projects} loading={loading} error={error} onChanged={refetch} />
      </div>
      <ChatInterface mode="projects" />
    </div>
  );
}
