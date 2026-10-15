"use client";

import { useCallback, useRef, useState } from "react";
import { motion } from "framer-motion";
import { CloudUpload, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { uploadDocuments } from "@/lib/api/upload";
import { useApp } from "@/lib/context/app-context";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface UploadCardProps {
  disabled?: boolean;
  onUploadComplete?: () => void;
}

export function UploadCard({ disabled, onUploadComplete }: UploadCardProps) {
  const { activeCollectionId, refresh } = useApp();
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [processing, setProcessing] = useState(false);

  const isDisabled = disabled || uploading || processing;

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.xlsx', '.csv', '.txt', '.md', '.markdown', '.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.webp', '.json', '.log'];
      const uploadableFiles = Array.from(files).filter((file) => {
        const ext = '.' + file.name.split('.').pop()?.toLowerCase();
        return ALLOWED_EXTENSIONS.includes(ext);
      });

      if (uploadableFiles.length === 0) {
        toast.error("Please upload supported document formats only (.pdf, .docx, .pptx, .xlsx, .csv, .txt, .md, .markdown, .png, .jpg, .jpeg, .tiff, .bmp, .webp, .json, .log).");
        return;
      }

      setUploading(true);
      setUploadProgress(0);

      let slowUploadTimer: NodeJS.Timeout | null = null;
      let toastId: string | number | null = null;

      slowUploadTimer = setTimeout(() => {
        toastId = toast.loading(
          "Embedding document... Large documents may take several minutes because embeddings are being generated.",
          { duration: Infinity }
        );
      }, 5000);

      try {
        const results = await uploadDocuments(uploadableFiles, {
          collectionId: activeCollectionId,
          onProgress: ({ progress }) => setUploadProgress(progress),
        });

        if (slowUploadTimer) clearTimeout(slowUploadTimer);
        if (toastId) toast.dismiss(toastId);

        setUploading(false);
        setProcessing(true);

        const alreadyExistsCount = results.filter((doc) => doc.status === "already_exists").length;
        const succeededCount = results.filter((doc) => doc.status === "indexed" || doc.status === "processing").length;
        const failedDocs = results.filter((doc) => doc.status === "failed");

        if (failedDocs.length > 0) {
          const errMsg = failedDocs
            .map((doc) => `${doc.name}: ${doc.error || "Processing failed"}`)
            .join(", ");
          if (succeededCount > 0) {
            toast.success(`${succeededCount} files uploaded successfully`);
          }
          throw new Error(errMsg);
        }

        if (alreadyExistsCount > 0 && succeededCount === 0) {
          toast.info("Already Indexed");
        } else if (alreadyExistsCount > 0) {
          toast.success(`${succeededCount} files uploaded, ${alreadyExistsCount} files Already Indexed`);
        } else {
          const indexing = results.some((doc) => doc.status === "processing");
          const what =
            uploadableFiles.length === 1 ? `"${uploadableFiles[0].name}"` : `${uploadableFiles.length} files`;
          toast.success(
            indexing
              ? `${what} uploaded. Indexing in the background; watch the status in Recent Documents.`
              : `${what} uploaded successfully`
          );
        }

        refresh();
        onUploadComplete?.();
      } catch (err) {
        if (slowUploadTimer) clearTimeout(slowUploadTimer);
        if (toastId) toast.dismiss(toastId);
        toast.error(
          err instanceof Error ? err.message : "Upload failed"
        );
      } finally {
        setUploading(false);
        setProcessing(false);
        setUploadProgress(0);
        if (inputRef.current) inputRef.current.value = "";
      }
    },
    [activeCollectionId, onUploadComplete, refresh]
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (!isDisabled) setIsDragging(true);
    },
    [isDisabled]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (isDisabled || !e.dataTransfer.files.length) return;
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles, isDisabled]
  );

  return (
    <motion.div
      id="upload"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
    >
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "rounded-2xl border-2 border-dashed bg-card px-4 py-3 transition-colors",
          isDragging ? "border-primary bg-primary/5" : "border-border/80 hover:border-primary/40",
          isDisabled && "pointer-events-none opacity-60"
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf,.docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.csv,text/csv,.txt,text/plain,.md,text/markdown,.markdown,text/markdown,.png,image/png,.jpg,image/jpeg,.jpeg,image/jpeg,.tiff,image/tiff,.bmp,image/bmp,.webp,image/webp,.json,application/json,.log,text/plain"
          multiple
          className="hidden"
          disabled={isDisabled}
          onChange={(e) => {
            if (e.target.files?.length) handleFiles(e.target.files);
          }}
        />
        <div className="flex items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            {uploading || processing ? <Loader2 className="size-5 animate-spin" /> : <CloudUpload className="size-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              {uploading
                ? `Uploading… ${uploadProgress}%`
                : processing
                  ? "Processing documents…"
                  : isDragging
                    ? "Release to upload"
                    : "Upload documents"}
            </p>
            <p className="truncate text-xs text-muted-foreground" title="PDF, DOCX, PPTX, XLSX, CSV, TXT, MD and images (PNG, JPG, WebP), up to 50 MB each">
              Drop files here · PDF, Word, PowerPoint, Excel, CSV, text, images · 50 MB max
            </p>
          </div>
          <Button size="sm" variant="secondary" className="shrink-0" disabled={isDisabled} onClick={() => inputRef.current?.click()}>
            Browse
          </Button>
        </div>
        {(uploading || processing) && (
          <Progress value={uploading ? uploadProgress : undefined} className="mt-3 h-1.5 w-full" />
        )}
      </div>
    </motion.div>
  );
}
