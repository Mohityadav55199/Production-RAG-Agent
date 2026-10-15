"use client";

import { ChatInterface } from "@/components/chat/chat-interface";
import { RecentDocuments } from "@/components/dashboard/recent-documents";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { UploadCard } from "@/components/dashboard/upload-card";
import { useDocuments } from "@/lib/hooks/use-documents";

export function RagWorkspace() {
  const { documents, stats, loading, error, refetch } = useDocuments({
    pollProcessing: true,
    kind: "documents",
  });

  return (
    <div className="grid items-start gap-4 lg:grid-cols-5 lg:gap-6">
      {/* Chat first: its input is on screen as soon as the page opens (above the uploads on a phone) */}
      <div className="lg:sticky lg:top-20 lg:order-2 lg:col-span-3">
        <ChatInterface mode="documents" />
      </div>

      {/* Add and manage documents */}
      <div className="space-y-4 lg:order-1 lg:col-span-2">
        <StatsCards stats={stats} loading={loading} error={error} compact />
        <UploadCard disabled={false} onUploadComplete={refetch} />
        <RecentDocuments documents={documents} loading={loading} error={error} />
      </div>
    </div>
  );
}
