import { describe, expect, it } from "vitest";
import { normalizeSources } from "@/lib/api/normalize";

describe("normalizeSources", () => {
  it("returns an empty list for anything that is not an array", () => {
    expect(normalizeSources(undefined)).toEqual([]);
    expect(normalizeSources(null)).toEqual([]);
    expect(normalizeSources({ sources: [] })).toEqual([]);
  });

  it("reads the backend snake_case fields", () => {
    const [source] = normalizeSources([
      {
        document_id: "d1",
        document_name: "handbook.md",
        chunk_text: "Remote work is allowed.",
        page: 3,
        chunk_index: 7,
        score: 0.82,
        images: ["img-1"],
      },
    ]);
    expect(source).toMatchObject({
      documentId: "d1",
      documentName: "handbook.md",
      chunkText: "Remote work is allowed.",
      page: 3,
      chunkIndex: 7,
      score: 0.82,
      images: ["img-1"],
    });
  });

  it("accepts alternative field names and defaults images to an empty list", () => {
    const [source] = normalizeSources([{ id: "d2", filename: "a.pdf", text: "hello", relevance: 0.5 }]);
    expect(source.documentId).toBe("d2");
    expect(source.documentName).toBe("a.pdf");
    expect(source.chunkText).toBe("hello");
    expect(source.score).toBe(0.5);
    expect(source.images).toEqual([]);
  });
});
