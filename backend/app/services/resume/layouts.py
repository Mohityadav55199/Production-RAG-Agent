"""
Base layouts from the user's own files.

- A .tex resume: its preamble becomes the template (see latex.check_preamble); the content is rendered with
  standard commands inside it.
- A .pdf resume: its look is measured (body font size, margins, serif or sans, section order) and turned
  into layout options for the built-in single-column template. The PDF's text is not used.
"""

from __future__ import annotations

import re
from collections import Counter

from app.services.resume.schemas import RenderOptions

_SECTION_PATTERNS = [
    ("summary", r"summary|profile|objective|about me"),
    ("skills", r"(technical )?skills|technologies|tech stack|competencies"),
    ("experience", r"(work |professional )?experience|employment( history)?|work history"),
    ("projects", r"(personal |selected )?projects"),
    ("education", r"education|academics?"),
    ("certifications", r"certifications?|certificates|licenses"),
    ("achievements", r"achievements|awards|honou?rs|accomplishments"),
]
_SANS_HINTS = ("sans", "helvetica", "arial", "calibri", "roboto", "opensans", "lato", "inter", "segoe", "verdana", "source sans")


def _nearest(value: float, choices: list) -> object:
    return min(choices, key=lambda c: abs(c - value))


def layout_from_pdf(pdf: bytes) -> tuple[RenderOptions, list[str]]:
    """Layout options that match a PDF resume, and notes on what was read."""
    import pymupdf

    sizes: Counter = Counter()
    fonts: Counter = Counter()
    lefts: list[float] = []
    rights: list[float] = []
    headings: list[str] = []
    width = 612.0
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        if doc.page_count == 0:
            raise ValueError("The PDF has no pages.")
        for page in list(doc)[:2]:
            width = page.rect.width
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in spans).strip()
                    for s in spans:
                        n = len(s["text"].strip())
                        sizes[round(s["size"] * 2) / 2] += n
                        fonts[s.get("font", "").lower()] += n
                    x0, _, x1, _ = line["bbox"]
                    lefts.append(x0)
                    rights.append(x1)
                    if len(text) <= 40:
                        headings.append(text)
    if not sizes:
        raise ValueError("No text could be read from this PDF (is it a scanned image?).")

    body_pt = sizes.most_common(1)[0][0]
    font_pt = _nearest(body_pt, [10, 11, 12])
    lefts.sort()
    rights.sort()
    left = lefts[max(0, len(lefts) // 20)]                     # ignore a few outliers (page numbers, icons)
    right = width - rights[min(len(rights) - 1, len(rights) * 19 // 20)]
    margin_in = _nearest(max(0.3, min(left, right) / 72), [0.5, 0.6, 0.75, 1.0])
    main_font = fonts.most_common(1)[0][0]
    font = "sans" if any(h in main_font.replace(" ", "") for h in _SANS_HINTS) else "serif"

    order: list[str] = []
    for text in headings:
        cleaned = re.sub(r"[^a-z ]", "", text.lower()).strip()
        for name, pattern in _SECTION_PATTERNS:
            if name not in order and re.fullmatch(pattern, cleaned):
                order.append(name)
    template = "student" if order[:1] == ["education"] else "skills_first" if order[:1] == ["skills"] else "classic"
    if body_pt <= 9.5:
        template = "compact" if template == "classic" else template

    options = RenderOptions(template=template, font_pt=font_pt, margin_in=margin_in, font=font,
                            section_order=order or None)
    notes = [
        f"Body text about {body_pt:g} pt, so {font_pt} pt",
        f"Margins about {min(left, right) / 72:.2f} in, so {margin_in} in",
        f"{'Sans-serif' if font == 'sans' else 'Serif'} font ({main_font or 'unknown'})",
        "Section order: " + (", ".join(order) if order else "not detected, kept the template's"),
    ]
    return options, notes
