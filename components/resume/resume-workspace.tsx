"use client";

import { useState } from "react";
import { FileSearch, History, Library, Sparkles } from "lucide-react";
import { AtsCheckPanel } from "@/components/resume/ats-check-panel";
import { HistoryPanel } from "@/components/resume/history-panel";
import { LibraryPanel, useResumeLibrary } from "@/components/resume/library-panel";
import { TailorPanel } from "@/components/resume/tailor-panel";
import { cn } from "@/lib/utils";

type Tab = "tailor" | "library" | "ats" | "history";

const tabs = [
  { id: "tailor", label: "Tailor", icon: Sparkles },
  { id: "library", label: "Resume library", icon: Library },
  { id: "ats", label: "ATS check", icon: FileSearch },
  { id: "history", label: "History", icon: History },
] as const;

export function ResumeWorkspace() {
  const [tab, setTab] = useState<Tab>("tailor");
  const [historyKey, setHistoryKey] = useState(0);
  const { resumes, loading, refetch } = useResumeLibrary();

  return (
    <div className="space-y-6">
      <div className="flex max-w-full overflow-x-auto">
        <div className="inline-flex rounded-lg border bg-background p-1" role="tablist">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
                tab === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="size-4" />
              {label}
              {id === "library" && resumes.length > 0 && (
                <span className="rounded-full bg-background/20 px-1.5 text-xs">{resumes.length}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tailor stays mounted so a running generation survives tab switches */}
      <div className={cn(tab !== "tailor" && "hidden")}>
        <TailorPanel
          resumes={resumes}
          onGoToLibrary={() => setTab("library")}
          onFinished={() => setHistoryKey((k) => k + 1)}
        />
      </div>
      {tab === "library" && <LibraryPanel resumes={resumes} loading={loading} onChanged={refetch} />}
      {tab === "ats" && <AtsCheckPanel />}
      {tab === "history" && <HistoryPanel refreshKey={historyKey} />}
    </div>
  );
}
