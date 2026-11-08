import { describe, expect, it } from "vitest";
import { formatBytes, formatRelativeTime } from "@/lib/utils";

describe("formatBytes", () => {
  it("formats zero and small values", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
  });

  it("scales to KB, MB and GB with one decimal", () => {
    expect(formatBytes(1024)).toBe("1 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5 MB");
    expect(formatBytes(2 * 1024 ** 3)).toBe("2 GB");
  });
});

describe("formatRelativeTime", () => {
  const ago = (ms: number) => new Date(Date.now() - ms);

  it("describes recent times", () => {
    expect(formatRelativeTime(ago(10_000))).toBe("Just now");
    expect(formatRelativeTime(ago(5 * 60_000))).toBe("5m ago");
    expect(formatRelativeTime(ago(3 * 3_600_000))).toBe("3h ago");
    expect(formatRelativeTime(ago(2 * 86_400_000))).toBe("2d ago");
  });

  it("falls back to a calendar date after a week", () => {
    expect(formatRelativeTime(ago(30 * 86_400_000))).toMatch(/^[A-Z][a-z]{2} \d{1,2}$/);
  });
});
