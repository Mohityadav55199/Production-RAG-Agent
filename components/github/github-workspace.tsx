"use client";

import { useEffect, useState } from "react";
import { ChatInterface } from "@/components/chat/chat-interface";
import { ProjectImportCard } from "@/components/dashboard/project-import-card";
import { ProjectsOverview } from "@/components/github/projects-overview";
import { useDocuments } from "@/lib/hooks/use-documents";

const WATCH_MS = 15 * 60 * 1000;

export function GithubWorkspace() {
  const { documents, loading, error, refetch } = useDocuments({
    pollProcessing: true,
    kind: "projects",
  });
  const [watchUntil, setWatchUntil] = useState(0);

  // Files appear one by one after an import, so keep refreshing for a while
  // even when nothing is "processing" at the exact moment of a poll.
  useEffect(() => {
    if (!watchUntil) return;
    const id = setInterval(() => {
      refetch();
      if (Date.now() > watchUntil) setWatchUntil(0);
    }, 4000);
    return () => clearInterval(id);
  }, [watchUntil, refetch]);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <ProjectImportCard
          onImportStarted={() => {
            setWatchUntil(Date.now() + WATCH_MS);
            refetch();
          }}
        />
        <ProjectsOverview documents={documents} loading={loading} error={error} onChanged={refetch} />
      </div>
      <ChatInterface mode="projects" />
    </div>
  );
}
