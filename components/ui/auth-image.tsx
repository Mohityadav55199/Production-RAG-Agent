"use client";

import { useEffect, useState } from "react";
import { ImageOff } from "lucide-react";
import { loadAssetUrl } from "@/lib/api/images";
import { cn } from "@/lib/utils";

interface AuthImageProps {
  assetId: string;
  size?: "thumb" | "full";
  alt: string;
  className?: string;
}

/** Shows an image stored on the server. It needs the login header, so it cannot be a plain <img src>. */
export function AuthImage({ assetId, size = "thumb", alt, className }: AuthImageProps) {
  const [state, setState] = useState<{ id: string; url: string | null; failed: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadAssetUrl(assetId, size)
      .then((url) => !cancelled && setState({ id: `${assetId}:${size}`, url, failed: false }))
      .catch(() => !cancelled && setState({ id: `${assetId}:${size}`, url: null, failed: true }));
    return () => {
      cancelled = true;
    };
  }, [assetId, size]);

  const current = state?.id === `${assetId}:${size}` ? state : null;

  if (current?.failed) {
    return (
      <span className={cn("flex items-center justify-center rounded-md bg-muted text-muted-foreground", className)} title="Image unavailable">
        <ImageOff className="size-4" aria-label="Image unavailable" />
      </span>
    );
  }
  if (!current?.url) {
    return <span className={cn("animate-pulse rounded-md bg-muted", className)} aria-hidden />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={current.url} alt={alt} referrerPolicy="no-referrer" className={className} />
  );
}
