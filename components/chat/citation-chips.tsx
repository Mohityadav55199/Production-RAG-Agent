"use client";

import { useState } from "react";
import type { QuerySource } from "@/lib/types";
import { CitationModal } from "@/components/chat/citation-modal";
import { ImageLightbox } from "@/components/ui/image-lightbox";
import { FileText, Code2, Sparkles, Image as ImageIcon } from "lucide-react";

interface CitationChipsProps {
  sources: QuerySource[];
  className?: string;
}

export function CitationChips({ sources, className = "" }: CitationChipsProps) {
  const [selectedSource, setSelectedSource] = useState<QuerySource | null>(null);
  const [lightbox, setLightbox] = useState<{ id: string; title: string } | null>(null);

  if (!sources || sources.length === 0) return null;

  return (
    <>
      <div className={`space-y-2 border-t border-border/60 pt-3 ${className}`}>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="font-semibold uppercase tracking-wider text-[10px] text-muted-foreground/90">
            Cited Sources ({sources.length})
          </span>
          <span className="text-[11px] text-muted-foreground/75">
            Click any source to inspect exact page or chunk
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {sources.map((source, i) => {
            const isCode =
              Boolean(source.documentName && /\.(ts|tsx|js|jsx|py|go|rs|cpp|c|java|json|yaml|yml|sql|sh)$/i.test(source.documentName)) ||
              Boolean(source.documentName && source.documentName.includes("/"));
            const scorePct = source.score !== undefined ? Math.round(source.score * 100) : null;
            const hasImages = Boolean(source.images && source.images.length > 0);

            return (
              <button
                key={`${source.documentId ?? "doc"}-${source.page ?? 0}-${source.chunkIndex ?? i}`}
                type="button"
                onClick={() => setSelectedSource(source)}
                className="group inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-background/80 hover:bg-muted/70 hover:border-primary/50 px-2.5 py-1 text-xs transition-all duration-150 text-left cursor-pointer shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                title={`Click to inspect chunk from ${source.documentName ?? "document"}`}
              >
                <div className="flex size-4 shrink-0 items-center justify-center rounded text-muted-foreground group-hover:text-primary transition-colors">
                  {isCode ? <Code2 className="size-3.5" /> : <FileText className="size-3.5" />}
                </div>

                <span className="font-medium max-w-[180px] sm:max-w-[220px] truncate text-foreground group-hover:text-primary transition-colors">
                  {source.documentName || "Document"}
                </span>

                {source.page !== undefined && source.page !== null && !source.documentName?.includes("/") && (
                  <span className="shrink-0 text-[11px] font-mono font-medium px-1.5 py-0.2 rounded bg-muted text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary transition-colors">
                    p.{source.page}
                  </span>
                )}

                {hasImages && (
                  <span className="shrink-0 text-muted-foreground" title="Contains figures">
                    <ImageIcon className="size-3 text-blue-500" />
                  </span>
                )}

                {scorePct !== null && (
                  <span className="shrink-0 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 opacity-80 group-hover:opacity-100 transition-opacity">
                    {scorePct}%
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Interactive Modal to view the exact chunk, page, full text, and images */}
      <CitationModal
        source={selectedSource}
        allSources={sources}
        isOpen={Boolean(selectedSource)}
        onClose={() => setSelectedSource(null)}
        onSelectSource={setSelectedSource}
        onOpenImage={(id, title) => setLightbox({ id, title })}
      />

      {/* Lightbox for zooming into extracted images */}
      {lightbox && (
        <ImageLightbox
          assetId={lightbox.id}
          title={lightbox.title}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}
