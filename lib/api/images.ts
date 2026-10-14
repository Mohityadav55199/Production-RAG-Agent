import { ApiError, apiFetch, authedFetch, getApiBase } from "@/lib/api/client";

export const MAX_CHAT_IMAGES = 3;
const MAX_FILE_BYTES = 25 * 1024 * 1024;       // refuse absurd files before even decoding them
const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/** An image the user attached to a question, already downscaled in the browser. */
export interface AttachedImage {
  id: string;
  name: string;
  mime: string;
  /** Base64 bytes without a data: prefix, as the API expects. */
  data: string;
  /** Local blob URL for showing a thumbnail. Release with releaseImages(). */
  previewUrl: string;
}

export function isImageFile(file: File): boolean {
  return ACCEPTED_TYPES.includes(file.type);
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not process the image."))), type, quality)
  );
}

/**
 * Shrinks an image so uploads stay small and fast. Screenshots (text, code) stay PNG when that is
 * reasonably small, because JPEG blurs small text; otherwise a high-quality JPEG is used.
 */
export async function downscaleImage(file: Blob, maxEdge = 1600): Promise<{ blob: Blob; mime: string }> {
  const bitmap = await createImageBitmap(file).catch(() => {
    throw new Error("That file could not be read as an image.");
  });
  try {
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Your browser could not process the image.");
    ctx.fillStyle = "#ffffff";                   // transparent PNGs become white, not black
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(bitmap, 0, 0, width, height);

    if (file.type === "image/png") {
      const pngBlob = await canvasToBlob(canvas, "image/png");
      if (pngBlob.size <= 1.5 * 1024 * 1024) return { blob: pngBlob, mime: "image/png" };
    }
    return { blob: await canvasToBlob(canvas, "image/jpeg", 0.88), mime: "image/jpeg" };
  } finally {
    bitmap.close();
  }
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(new Error("Could not read the image."));
    reader.readAsDataURL(blob);
  });
}

/** Validates and prepares one file for attaching to a question. Throws an Error with a user-facing message. */
export async function prepareImage(file: File): Promise<AttachedImage> {
  if (!isImageFile(file)) {
    throw new Error(`"${file.name || "That file"}" is not a supported image (use PNG, JPEG, WebP or GIF).`);
  }
  if (file.size > MAX_FILE_BYTES) {
    throw new Error(`"${file.name}" is larger than ${MAX_FILE_BYTES / (1024 * 1024)} MB.`);
  }
  const { blob, mime } = await downscaleImage(file);
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: file.name || "pasted image",
    mime,
    data: await toBase64(blob),
    previewUrl: URL.createObjectURL(blob),
  };
}

export function releaseImages(images: { previewUrl: string }[]): void {
  images.forEach((image) => URL.revokeObjectURL(image.previewUrl));
}

/** Image files from a clipboard or drag-and-drop event. */
export function imageFilesFrom(items: DataTransfer | null): File[] {
  if (!items) return [];
  return Array.from(items.files).filter(isImageFile);
}

// ── Stored images (document figures, uploaded pictures) ─────────────────────────────────────────

const assetCache = new Map<string, Promise<string>>();

/**
 * Loads a stored image as a blob URL. <img src> cannot send the login header, so the image is fetched
 * with it. Results are cached per image and size for the life of the page.
 */
export function loadAssetUrl(assetId: string, size: "thumb" | "full" = "thumb"): Promise<string> {
  const key = `${assetId}:${size}`;
  const cached = assetCache.get(key);
  if (cached) return cached;
  const request = authedFetch(`${getApiBase()}/assets/${assetId}?size=${size}`)
    .then(async (res) => {
      if (!res.ok) throw new ApiError(res.status, "The image could not be loaded.");
      return URL.createObjectURL(await res.blob());
    })
    .catch((err) => {
      assetCache.delete(key);                    // let a later render try again
      throw err;
    });
  assetCache.set(key, request);
  return request;
}

// ── Code screenshots ───────────────────────────────────────────────────────────────────────────

export interface ExtractedCode {
  text: string;
  language: string | null;
  engine: "gemini" | "ocr";
  note: string | null;
}

/** Reads the code out of a screenshot so it can be compared. */
export async function extractCodeFromImage(file: File): Promise<ExtractedCode> {
  if (!isImageFile(file)) throw new Error("Choose a PNG, JPEG, WebP or GIF screenshot.");
  const { blob, mime } = await downscaleImage(file, 2000);     // larger than chat: small code text must stay legible
  const form = new FormData();
  form.append("file", new File([blob], mime === "image/png" ? "screenshot.png" : "screenshot.jpg", { type: mime }));
  return apiFetch<ExtractedCode>("/compare/extract-code", { method: "POST", body: form, timeout: 90000 });
}
