"use client";

import { useCallback, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Briefcase, FileSearch, History, Library, Pencil, Sparkles } from "lucide-react";
import { AtsCheckPanel } from "@/components/resume/ats-check-panel";
import { DraftEditor } from "@/components/resume/draft-editor";
import { HistoryPanel } from "@/components/resume/history-panel";
import { JobTracker } from "@/components/resume/job-tracker";
import { LibraryPanel, useResumeLibrary } from "@/components/resume/library-panel";
import { TailorPanel } from "@/components/resume/tailor-panel";
import { TabBar, panelId, tabId, type TabItem } from "@/components/ui/tab-bar";
import type { JobApplication } from "@/lib/api/resume";
import { cn } from "@/lib/utils";

type Tab = "tailor" | "editor" | "tracker" | "library" | "ats" | "history";

const PREFIX = "resume";
const RUN_ID = /^[0-9a-f-]{36}$/i;

export function ResumeWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // The open run lives in the URL (/resume?run=<id>), so a reload or a shared link reopens the same draft
  const runParam = searchParams.get("run");
  const initialRun = runParam && RUN_ID.test(runParam) ? runParam : null;
  const [editingId, setEditingId] = useState<string | null>(initialRun);
  const [tab, setTab] = useState<Tab>(initialRun ? "editor" : "tailor");
  const [focusOutreach, setFocusOutreach] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);
  const { resumes, loading, refetch } = useResumeLibrary();

  const openEditor = useCallback(
    (generationId: string, outreach = false) => {
      setEditingId(generationId);
      setFocusOutreach(outreach);
      setTab("editor");
      router.replace(`${pathname}?run=${generationId}${outreach ? "#outreach" : ""}`, { scroll: false });
    },
    [pathname, router]
  );

  const openOutreach = (job: JobApplication) => {
    if (job.resume_generation_id) openEditor(job.resume_generation_id, true);
  };

  const tabs: readonly TabItem<Tab>[] = [
    { id: "tailor", label: "Tailor", icon: Sparkles },
    ...(editingId ? [{ id: "editor" as const, label: "Editor", icon: Pencil }] : []),
    { id: "tracker", label: "Job tracker", icon: Briefcase },
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
          onOpenEditor={(id) => openEditor(id)}
        />,
        true
      )}
      {/* The editor stays mounted too, so unsaved edits survive a look at another tab */}
      {editingId &&
        panel(
          "editor",
          <DraftEditor
            key={editingId}
            generationId={editingId}
            focusOutreach={focusOutreach && tab === "editor"}
            onChanged={() => setHistoryKey((k) => k + 1)}
          />,
          true
        )}
      {panel("tracker", <JobTracker onOpenOutreach={openOutreach} />)}
      {panel("library", <LibraryPanel resumes={resumes} loading={loading} onChanged={refetch} />)}
      {panel("ats", <AtsCheckPanel />)}
      {panel("history", <HistoryPanel refreshKey={historyKey} onOpen={(id) => openEditor(id)} />)}
    </div>
  );
}
