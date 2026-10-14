"use client";

import { ChatInterface } from "@/components/chat/chat-interface";
import { HealthStatus } from "@/components/dashboard/health-status";
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
    <div className="space-y-6">
      <StatsCards stats={stats} loading={loading} error={error} />

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <UploadCard disabled={false} onUploadComplete={refetch} />
        </div>
        <div className="lg:col-span-3">
          <RecentDocuments documents={documents} loading={loading} error={error} />
        </div>
      </div>

      <ChatInterface mode="documents" />

      <HealthStatus />
    </div>
  );
}
