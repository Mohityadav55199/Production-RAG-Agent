"use client";

import { AuthImage } from "@/components/ui/auth-image";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

interface ImageLightboxProps {
  /** The stored image to show full size, or null when closed. */
  assetId: string | null;
  title?: string;
  onClose: () => void;
}

export function ImageLightbox({ assetId, title = "Image", onClose }: ImageLightboxProps) {
  return (
    <Dialog open={assetId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogTitle className="truncate pr-8 text-base">{title}</DialogTitle>
        <DialogDescription className="sr-only">Full size view of the image</DialogDescription>
        {assetId && (
          <AuthImage
            assetId={assetId}
            size="full"
            alt={title}
            className="mx-auto max-h-[75vh] w-auto max-w-full rounded-lg object-contain"
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
