"use client";

import { useState } from "react";
import { ArrowLeftRight, MessageSquare } from "lucide-react";
import { ChatInterface } from "@/components/chat/chat-interface";
import { ComparePanel } from "@/components/chat/compare-panel";
import { cn } from "@/lib/utils";

type Tab = "ask" | "compare";

export function ChatWorkspace() {
  const [tab, setTab] = useState<Tab>("ask");

  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-lg border bg-background p-1" role="tablist">
        {(
          [
            { id: "ask", label: "Ask", icon: MessageSquare },
            { id: "compare", label: "Compare", icon: ArrowLeftRight },
          ] as const
        ).map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-4 py-1.5 text-sm font-medium transition-colors",
              tab === id
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Keep the chat mounted so switching tabs doesn't lose the conversation */}
      <div className={cn(tab !== "ask" && "hidden")}>
        <ChatInterface />
      </div>
      {tab === "compare" && <ComparePanel />}
    </div>
  );
}
