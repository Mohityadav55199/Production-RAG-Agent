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
    <div className="space-y-4">
      <HealthStatus compact />
      <StatsCards stats={stats} loading={loading} error={error} />

      <div className="grid items-start gap-6 lg:grid-cols-5">
        {/* Left: add and manage documents */}
        <div className="space-y-6 lg:col-span-2">
          <UploadCard disabled={false} onUploadComplete={refetch} />
          <RecentDocuments documents={documents} loading={loading} error={error} />
        </div>

        {/* Right: chat stays in view while the left column scrolls */}
        <div className="lg:sticky lg:top-24 lg:col-span-3">
          <ChatInterface mode="documents" />
        </div>
      </div>
    </div>
  );
}
