"use client";

import type { ReactNode } from "react";
import { ChatInterface } from "@/components/chat/chat-interface";
import { ProjectImportCard } from "@/components/dashboard/project-import-card";
import { ProjectsOverview } from "@/components/github/projects-overview";
import { ChatWorkspace } from "@/components/layout/chat-workspace";
import { useProjects } from "@/lib/hooks/use-projects";

export function GithubWorkspace({ header }: { header: ReactNode }) {
  const { projects, loading, error, refetch, watch } = useProjects();

  return (
    <ChatWorkspace
      header={header}
      chat={<ChatInterface mode="projects" />}
      side={
        <>
          <ProjectImportCard onImportStarted={watch} />
          <ProjectsOverview projects={projects} loading={loading} error={error} onChanged={refetch} />
        </>
      }
    />
  );
}
