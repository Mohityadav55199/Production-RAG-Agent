"use client";

import type { ReactNode } from "react";
import { ChatInterface } from "@/components/chat/chat-interface";
import { RecentDocuments } from "@/components/dashboard/recent-documents";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { UploadCard } from "@/components/dashboard/upload-card";
import { ChatWorkspace } from "@/components/layout/chat-workspace";
import { useDocuments } from "@/lib/hooks/use-documents";

export function RagWorkspace({ header }: { header: ReactNode }) {
  const { documents, stats, loading, error, refetch } = useDocuments({
    pollProcessing: true,
    kind: "documents",
  });

  return (
    <ChatWorkspace
      header={header}
      chat={<ChatInterface mode="documents" />}
      side={
        <>
          <StatsCards stats={stats} loading={loading} error={error} compact />
          <UploadCard disabled={false} onUploadComplete={refetch} />
          <RecentDocuments documents={documents} loading={loading} error={error} />
        </>
      }
    />
  );
}
