"use client";

import { useState } from "react";
import { FileSearch, History, Library, Pencil, Sparkles } from "lucide-react";
import { AtsCheckPanel } from "@/components/resume/ats-check-panel";
import { DraftEditor } from "@/components/resume/draft-editor";
import { HistoryPanel } from "@/components/resume/history-panel";
import { LibraryPanel, useResumeLibrary } from "@/components/resume/library-panel";
import { TailorPanel } from "@/components/resume/tailor-panel";
import { TabBar, panelId, tabId, type TabItem } from "@/components/ui/tab-bar";
import { cn } from "@/lib/utils";

type Tab = "tailor" | "editor" | "library" | "ats" | "history";

const PREFIX = "resume";

export function ResumeWorkspace() {
  const [tab, setTab] = useState<Tab>("tailor");
  const [historyKey, setHistoryKey] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const { resumes, loading, refetch } = useResumeLibrary();

  const openEditor = (generationId: string) => {
    setEditingId(generationId);
    setTab("editor");
  };

  const tabs: readonly TabItem<Tab>[] = [
    { id: "tailor", label: "Tailor", icon: Sparkles },
    ...(editingId ? [{ id: "editor" as const, label: "Editor", icon: Pencil }] : []),
    { id: "library", label: "Resume library", icon: Library, badge: resumes.length },
    { id: "ats", label: "ATS check", icon: FileSearch },
    { id: "history", label: "History", icon: History },
  ];

  const panel = (id: Tab, children: React.ReactNode, keepMounted = false) =>
    keepMounted || tab === id ? (
      <div
        role="tabpanel"
        id={panelId(PREFIX, id)}
        aria-labelledby={tabId(PREFIX, id)}
        className={cn(tab !== id && "hidden")}
      >
        {children}
      </div>
    ) : null;

  return (
    <div className="space-y-6">
      <TabBar tabs={tabs} value={tab} onChange={setTab} idPrefix={PREFIX} label="Resume tools" />

      {/* Tailor stays mounted so a running generation survives tab switches */}
      {panel(
        "tailor",
        <TailorPanel
          resumes={resumes}
          onGoToLibrary={() => setTab("library")}
          onFinished={() => setHistoryKey((k) => k + 1)}
          onOpenEditor={openEditor}
        />,
        true
      )}
      {editingId &&
        panel(
          "editor",
          <DraftEditor key={editingId} generationId={editingId} onChanged={() => setHistoryKey((k) => k + 1)} />
        )}
      {panel("library", <LibraryPanel resumes={resumes} loading={loading} onChanged={refetch} />)}
      {panel("ats", <AtsCheckPanel />)}
      {panel("history", <HistoryPanel refreshKey={historyKey} onOpen={openEditor} />)}
    </div>
  );
}
