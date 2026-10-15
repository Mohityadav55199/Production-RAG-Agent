"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AuthImage } from "@/components/ui/auth-image";
import type { QuerySource } from "@/lib/types";
import {
  FileText,
  Code2,
  Copy,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Layers,
  Sparkles,
} from "lucide-react";

interface CitationModalProps {
  source: QuerySource | null;
  allSources?: QuerySource[];
  isOpen: boolean;
  onClose: () => void;
  onSelectSource?: (source: QuerySource) => void;
  onOpenImage?: (assetId: string, title: string) => void;
}

export function CitationModal({
  source,
  allSources = [],
  isOpen,
  onClose,
  onSelectSource,
  onOpenImage,
}: CitationModalProps) {
  const [copied, setCopied] = useState(false);
  const [copiedCitation, setCopiedCitation] = useState(false);
  const [monospace, setMonospace] = useState(false);

  if (!source) return null;

  const currentIndex = allSources.findIndex(
    (s) =>
      s.documentId === source.documentId &&
      s.page === source.page &&
      s.chunkIndex === source.chunkIndex
  );
  const hasMultiple = allSources.length > 1;

  const handlePrev = () => {
    if (!onSelectSource || currentIndex <= 0) return;
    onSelectSource(allSources[currentIndex - 1]);
  };

  const handleNext = () => {
    if (!onSelectSource || currentIndex < 0 || currentIndex >= allSources.length - 1) return;
    onSelectSource(allSources[currentIndex + 1]);
  };

  const textToDisplay = source.fullText || source.chunkText || "No text available for this chunk.";
  const isCode =
    Boolean(source.documentName && /\.(ts|tsx|js|jsx|py|go|rs|cpp|c|java|json|yaml|yml|sql|sh)$/i.test(source.documentName)) ||
    Boolean(source.documentName && source.documentName.includes("/"));

  const citationText = source.documentName
    ? source.page && !source.documentName.includes("/")
      ? `(${source.documentName}, p. ${source.page})`
      : `(${source.documentName})`
    : "Source citation";

  const handleCopyText = async () => {
    try {
      await navigator.clipboard.writeText(textToDisplay);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard error
    }
  };

  const handleCopyCitation = async () => {
    try {
      await navigator.clipboard.writeText(citationText);
      setCopiedCitation(true);
      setTimeout(() => setCopiedCitation(false), 2000);
    } catch {
      // ignore clipboard error
    }
  };

  const scorePct = source.score !== undefined ? Math.round(source.score * 100) : null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col p-0 overflow-hidden border-border/80 shadow-2xl">
        {/* Header */}
        <DialogHeader className="p-5 pb-3 border-b border-border/60 bg-muted/20">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary border border-primary/20">
                {isCode ? <Code2 className="size-4" /> : <FileText className="size-4" />}
              </div>
              <div className="min-w-0">
                <DialogTitle className="text-base font-semibold truncate text-foreground">
                  {source.documentName ?? "Document Chunk"}
                </DialogTitle>
                <div className="flex flex-wrap items-center gap-1.5 mt-1 text-xs text-muted-foreground">
                  {source.page !== undefined && source.page !== null && (
                    <Badge variant="outline" className="px-1.5 py-0 text-[11px] font-medium border-border/80">
                      Page {source.page}
                    </Badge>
                  )}
                  {source.chunkIndex !== undefined && (
                    <Badge variant="outline" className="px-1.5 py-0 text-[11px] font-medium border-border/80">
                      Chunk #{source.chunkIndex}
                    </Badge>
                  )}
                  {scorePct !== null && (
                    <Badge
                      variant="secondary"
                      className="px-1.5 py-0 text-[11px] font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20"
                    >
                      <Sparkles className="size-3 mr-0.5" />
                      {scorePct}% match
                    </Badge>
                  )}
                </div>
              </div>
            </div>

            {hasMultiple && (
              <div className="flex items-center gap-1 shrink-0 text-xs text-muted-foreground">
                <Button
                  variant="outline"
                  size="icon"
                  className="size-7"
                  disabled={currentIndex <= 0}
                  onClick={handlePrev}
                  title="Previous source"
                  aria-label="Previous source"
                >
                  <ChevronLeft className="size-3.5" />
                </Button>
                <span className="px-1 font-mono text-[11px]">
                  {currentIndex + 1}/{allSources.length}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  className="size-7"
                  disabled={currentIndex < 0 || currentIndex >= allSources.length - 1}
                  onClick={handleNext}
                  title="Next source"
                  aria-label="Next source"
                >
                  <ChevronRight className="size-3.5" />
                </Button>
              </div>
            )}
          </div>
        </DialogHeader>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Action Bar */}
          <div className="flex items-center justify-between text-xs text-muted-foreground bg-muted/40 px-3 py-1.5 rounded-lg border border-border/50">
            <span className="flex items-center gap-1.5 font-medium">
              <Layers className="size-3.5" />
              Retrieved context chunk ({textToDisplay.length} characters)
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setMonospace(!monospace)}
                className="px-2 py-0.5 rounded text-[11px] hover:bg-background transition-colors border border-transparent hover:border-border"
              >
                {monospace ? "Prose font" : "Monospace font"}
              </button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopyText}
                className="h-6 px-2 text-xs gap-1"
              >
                {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
                {copied ? "Copied" : "Copy text"}
              </Button>
            </div>
          </div>

          {/* Chunk Text Container */}
          <div
            className={`rounded-xl border border-border/70 bg-card p-4 text-xs leading-relaxed overflow-x-auto whitespace-pre-wrap select-text selection:bg-primary/20 ${
              monospace || isCode ? "font-mono bg-muted/20" : ""
            }`}
          >
            {textToDisplay}
          </div>

          {/* Figures / Extracted Page Images if any */}
          {source.images && source.images.length > 0 && (
            <div className="space-y-2 border-t border-border/60 pt-3">
              <p className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                Extracted figures & images on this page
              </p>
              <div className="flex flex-wrap gap-2.5">
                {source.images.map((assetId, i) => (
                  <button
                    key={assetId}
                    type="button"
                    onClick={() => onOpenImage?.(assetId, source.documentName ?? "Document figure")}
                    className="group relative overflow-hidden rounded-lg border border-border bg-muted/30 p-1 hover:border-primary/50 transition-colors"
                  >
                    <AuthImage
                      assetId={assetId}
                      alt={`Figure ${i + 1}`}
                      className="size-24 object-cover rounded-md group-hover:scale-105 transition-transform duration-200"
                    />
                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity text-white text-[11px] font-medium">
                      Enlarge
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-3 px-5 border-t border-border/60 bg-muted/20 flex items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 truncate text-muted-foreground">
            <span className="truncate font-mono text-[11px]">Citation: {citationText}</span>
            <button
              type="button"
              onClick={handleCopyCitation}
              className="hover:text-foreground text-muted-foreground p-1 transition-colors"
              title="Copy citation string"
              aria-label="Copy citation string"
            >
              {copiedCitation ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
            </button>
          </div>

          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
