"use client";

import { ChatInterface } from "@/components/chat/chat-interface";
import { ProjectImportCard } from "@/components/dashboard/project-import-card";
import { ProjectsOverview } from "@/components/github/projects-overview";
import { useProjects } from "@/lib/hooks/use-projects";

export function GithubWorkspace() {
  const { projects, loading, error, refetch, watch } = useProjects();

  return (
    <div className="grid items-start gap-4 lg:grid-cols-5 lg:gap-6">
      {/* Chat first: its input is on screen as soon as the page opens (above the import on a phone) */}
      <div className="lg:sticky lg:top-20 lg:order-2 lg:col-span-3">
        <ChatInterface mode="projects" />
      </div>

      {/* Import and manage projects */}
      <div className="space-y-4 lg:order-1 lg:col-span-2">
        <ProjectImportCard onImportStarted={watch} />
        <ProjectsOverview projects={projects} loading={loading} error={error} onChanged={refetch} />
      </div>
    </div>
  );
}
