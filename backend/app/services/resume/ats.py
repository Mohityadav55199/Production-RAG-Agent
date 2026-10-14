"""
ATS scoring.

This is an *estimate*: there is no single real ATS (Workday, Greenhouse, Lever
and Taleo all parse differently, and most never show candidates a score). The
score is computed by code, not model opinion, from four components:

    keywords   45%  coverage of the job description's must-have / nice-to-have terms
    parsing    25%  can text, contact details and standard sections be extracted?
    format     15%  length, bullets, action verbs, quantified impact
    fit        15%  LLM judge against a fixed rubric (optional)

For PDFs the text is extracted exactly as a parser would see it, including a
check for multi-column layouts and image-only content.
"""

import re
from dataclasses import dataclass, field

from app.services.resume.schemas import JDAnalysis

WEIGHTS_WITH_JD = {"keywords": 45, "parsing": 25, "format": 15, "fit": 15}
WEIGHTS_NO_JD = {"parsing": 60, "format": 40}

SYNONYM_GROUPS = [
    {"javascript", "js"}, {"typescript", "ts"}, {"node.js", "nodejs", "node"},
    {"react", "react.js", "reactjs"}, {"vue", "vue.js", "vuejs"}, {"next.js", "nextjs"},
    {"kubernetes", "k8s"}, {"postgresql", "postgres"}, {"mongodb", "mongo"},
    {"c++", "cpp"}, {"machine learning", "ml"}, {"natural language processing", "nlp"},
    {"amazon web services", "aws"}, {"google cloud platform", "gcp", "google cloud"},
    {"rest", "restful", "rest api", "rest apis", "restful api", "restful apis"},
    {"ci/cd", "cicd", "continuous integration"}, {"large language models", "llm", "llms"},
    {"retrieval augmented generation", "retrieval-augmented generation", "rag"},
    {"object oriented programming", "oop", "object-oriented programming"},
    {"data structures and algorithms", "dsa", "data structures", "algorithms"},
    {"sql", "structured query language"}, {"html", "html5"}, {"css", "css3"},
    {"golang", "go"},
]
_SYNONYMS: dict[str, set[str]] = {}
for _group in SYNONYM_GROUPS:
    for _term in _group:
        _SYNONYMS[_term] = _group

# Used for the deterministic fallback when the JD can't be analysed by the LLM
TECH_TERMS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust", "kotlin", "swift",
    "php", "ruby", "scala", "sql", "nosql", "html", "css", "react", "angular", "vue", "next.js", "node.js",
    "express", "django", "flask", "fastapi", "spring boot", "spring", ".net", "graphql", "rest", "grpc",
    "microservices", "docker", "kubernetes", "aws", "azure", "gcp", "terraform", "jenkins", "ci/cd", "git",
    "linux", "postgresql", "mysql", "mongodb", "redis", "kafka", "rabbitmq", "elasticsearch", "tensorflow",
    "pytorch", "pandas", "numpy", "scikit-learn", "machine learning", "deep learning", "nlp", "llm",
    "langchain", "langgraph", "rag", "data structures", "algorithms", "system design", "agile", "scrum",
    "unit testing", "junit", "pytest", "jest", "tailwind", "redux", "oauth", "jwt", "websockets",
]

SECTION_PATTERNS = {
    "experience": r"\b(work experience|professional experience|experience|employment)\b",
    "education": r"\beducation\b",
    "skills": r"\b(technical skills|skills)\b",
    "projects": r"\bprojects?\b",
}

ACTION_VERBS = {
    "built", "developed", "designed", "implemented", "created", "led", "managed", "improved", "optimized",
    "reduced", "increased", "launched", "delivered", "automated", "architected", "engineered", "integrated",
    "deployed", "migrated", "refactored", "analyzed", "collaborated", "mentored", "established", "streamlined",
    "spearheaded", "owned", "drove", "shipped", "wrote", "maintained", "configured", "tested", "debugged",
    "resolved", "enhanced", "accelerated", "coordinated", "established", "initiated", "executed", "scaled",
    "authored", "researched", "trained", "secured", "monitored", "contributed", "achieved", "won", "ranked",
}


@dataclass
class Component:
    key: str
    label: str
    score: int          # 0-100
    weight: int         # percent of total
    details: str = ""
    findings: list[str] = field(default_factory=list)


@dataclass
class AtsReport:
    total: int
    components: list[Component]
    matched: list[str]
    missing_must: list[str]
    missing_nice: list[str]
    fixes: list[str]
    pdf_checked: bool
    has_jd: bool

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "components": [vars(c) for c in self.components],
            "matched": self.matched,
            "missing_must": self.missing_must,
            "missing_nice": self.missing_nice,
            "fixes": self.fixes,
            "pdf_checked": self.pdf_checked,
            "has_jd": self.has_jd,
        }


# ── PDF text as a parser sees it ─────────────────────────────────────────────

def pdf_text_and_meta(pdf: bytes) -> tuple[str, dict]:
    import pymupdf

    meta = {"pages": 0, "images": 0, "two_column": False, "chars": 0}
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc
    with doc:
        texts = []
        left = right = 0
        for page in doc:
            texts.append(page.get_text("text", sort=True))
            meta["images"] += len(page.get_images())
            width = page.rect.width
            for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
                if len(str(text).strip()) < 40:
                    continue
                if x1 < width * 0.55:
                    left += 1
                elif x0 > width * 0.45:
                    right += 1
        meta["pages"] = len(doc)
        meta["two_column"] = left >= 3 and right >= 3
    text = "\n".join(texts)
    meta["chars"] = len(text.strip())
    return text, meta


# ── Keyword matching ─────────────────────────────────────────────────────────

def _variants(term: str) -> set[str]:
    t = term.lower().strip()
    return {t} | _SYNONYMS.get(t, set())


def _term_regex(variant: str) -> re.Pattern:
    body = re.escape(variant)
    plural = "s?" if variant[-1:].isalpha() else ""
    return re.compile(rf"(?<![a-z0-9]){body}{plural}(?![a-z0-9])", re.IGNORECASE)


# Terms that are also everyday words/letters ("go to market", "R&D", "Plan C"). They only count when
# written the way a skill is: capitalised AND either a list item or introduced by a cue word.
_AMBIGUOUS_TERMS = {"go", "r", "c"}
_CUE_WORDS = r"(?:in|with|using|and|or|of|for|on|plus|including|like|via|from)"


def _ambiguous_match(variant: str, text: str) -> bool:
    written = variant.upper() if len(variant) == 1 else variant.capitalize()   # R, C, Go
    for token in re.split(r"[,;:|/\u2022\n()\[\]]+", text):
        if token.strip() == written:
            return True
    return bool(re.search(rf"(?i:\b{_CUE_WORDS})\s+{written}(?![A-Za-z0-9+#])", text))


def term_in_text(term: str, text: str) -> bool:
    for variant in _variants(term):
        if variant in _AMBIGUOUS_TERMS:
            if _ambiguous_match(variant, text):
                return True
        elif _term_regex(variant).search(text):
            return True
    return False


def fallback_jd_analysis(jd_text: str) -> JDAnalysis:
    """Deterministic JD analysis used when the LLM is unavailable."""
    found = [t for t in TECH_TERMS if term_in_text(t, jd_text)]
    return JDAnalysis(must_have=found[:14], nice_to_have=found[14:24])


# ── Components ───────────────────────────────────────────────────────────────

def _keyword_component(text: str, jd: JDAnalysis, weight: int) -> tuple[Component, list[str], list[str], list[str]]:
    must = list(dict.fromkeys(jd.must_have))
    nice = [t for t in dict.fromkeys(jd.nice_to_have) if t not in must]
    matched = [t for t in must + nice if term_in_text(t, text)]
    missing_must = [t for t in must if t not in matched]
    missing_nice = [t for t in nice if t not in matched]

    earned = 2 * sum(t in matched for t in must) + sum(t in matched for t in nice)
    possible = 2 * len(must) + len(nice)
    score = round(100 * earned / possible) if possible else 0

    findings = []
    if missing_must:
        findings.append("Missing required terms: " + ", ".join(missing_must[:10]))
    if missing_nice:
        findings.append("Missing nice-to-have terms: " + ", ".join(missing_nice[:8]))
    detail = f"{len(matched)} of {len(must) + len(nice)} job-description terms found"
    return Component("keywords", "Keyword match", score, weight, detail, findings), matched, missing_must, missing_nice


def _parsing_component(text: str, meta: dict | None, weight: int) -> Component:
    checks: list[tuple[str, bool, int]] = []  # (finding if failed, passed, points)
    checks.append(("No email address found in the extracted text.", bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)), 15))
    checks.append(("No phone number found in the extracted text.", bool(re.search(r"\+?\d[\d\s().-]{8,}\d", text)), 10))

    lower = text.lower()
    sections = [name for name, pat in SECTION_PATTERNS.items() if re.search(pat, lower)]
    missing_sections = [s for s in SECTION_PATTERNS if s not in sections]
    checks.append((f"Standard section headings not detected: {', '.join(missing_sections)}.", len(sections) >= 3, 25))
    if len(sections) == 2:
        checks[-1] = (checks[-1][0], False, 25)

    checks.append(("Very little text could be extracted (is the PDF image-based?).", len(text.strip()) >= 400, 15))
    odd = sum(1 for c in text if ord(c) > 0x2FF or c == "�")
    checks.append(("Extracted text contains many unreadable characters.", odd <= max(3, len(text) * 0.02), 10))
    dates = re.findall(r"(?:19|20)\d{2}\s*(?:-|--|to|–|—)\s*(?:(?:19|20)\d{2}|present|current)|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}", lower)
    checks.append(("Fewer than two dates found; use clear date ranges like 'Jun 2023 - Present'.", len(dates) >= 2, 10))

    if meta is not None:
        checks.append(("Two-column layout detected; many ATS read columns in the wrong order.", not meta["two_column"], 10))
        checks.append(("Images found; ATS cannot read text inside images.", meta["images"] == 0, 5))

    total_points = sum(p for _, _, p in checks)
    earned = sum(p for _, ok, p in checks if ok)
    findings = [msg for msg, ok, _ in checks if not ok]
    score = round(100 * earned / total_points)
    return Component("parsing", "Parseability", score, weight, f"{len(sections)} of 4 standard sections detected", findings)


def _bullets(text: str) -> list[str]:
    # Many PDFs extract the bullet glyph on its own line, with the text on the next one
    text = re.sub(r"(?m)^[ \t]*([\u2022\u25aa\u25cf\u25e6\u2023\u2219\u00b7])[ \t]*\n+[ \t]*", r"\1 ", text)
    out = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:[-•*▪●]|•)\s*(.+)$", line)
        if m and len(m.group(1).split()) >= 4:
            out.append(m.group(1).strip())
    return out


def _format_component(text: str, meta: dict | None, plain_bullets: list[str] | None, weight: int) -> Component:
    findings: list[str] = []
    points = 0

    pages = meta["pages"] if meta else None
    if pages is None or pages <= 2:
        points += 30
    else:
        findings.append(f"Resume is {pages} pages; keep it to 1-2 pages.")

    bullets = plain_bullets if plain_bullets is not None else _bullets(text)
    if len(bullets) >= 6:
        points += 20
    else:
        findings.append("Use bullet points for achievements (at least 6 detected bullets).")

    if bullets:
        verbs = sum(1 for b in bullets if b.split()[0].lower().strip(",.:;") in ACTION_VERBS or b.split()[0].lower().endswith("ed"))
        if verbs / len(bullets) >= 0.7:
            points += 20
        else:
            findings.append("Start more bullets with strong action verbs (Built, Reduced, Led...).")
        quantified = sum(1 for b in bullets if re.search(r"\d|%|\$", b))
        if quantified / len(bullets) >= 0.3:
            points += 20
        else:
            findings.append("Quantify impact: fewer than 30% of bullets contain numbers or percentages.")
    else:
        findings.append("No bullet points detected.")

    if not re.search(r"\b(i am|i have|i was|my )\b", text.lower()):
        points += 10
    else:
        findings.append("Avoid first-person wording ('I', 'my') in a resume.")

    return Component("format", "Format & content", min(points, 100), weight, f"{len(bullets)} bullets detected", findings)


def build_report(
    text: str,
    jd: JDAnalysis | None = None,
    meta: dict | None = None,
    fit: tuple[int, str] | None = None,
    plain_bullets: list[str] | None = None,
) -> AtsReport:
    """Score resume text. ``meta`` comes from pdf_text_and_meta; ``fit`` = (0-100, reason) from the LLM judge."""
    has_jd = jd is not None
    weights = dict(WEIGHTS_WITH_JD if has_jd else WEIGHTS_NO_JD)
    if has_jd and fit is None:           # redistribute the fit weight proportionally
        extra = weights.pop("fit")
        rest = sum(weights.values())
        weights = {k: v + extra * v / rest for k, v in weights.items()}

    components: list[Component] = []
    matched: list[str] = []
    missing_must: list[str] = []
    missing_nice: list[str] = []

    if has_jd:
        comp, matched, missing_must, missing_nice = _keyword_component(text, jd, weights["keywords"])
        components.append(comp)
    components.append(_parsing_component(text, meta, weights["parsing"]))
    components.append(_format_component(text, meta, plain_bullets, weights["format"]))
    if has_jd and fit is not None:
        components.append(Component("fit", "Role fit (AI judge)", fit[0], weights["fit"], fit[1], []))

    total = round(sum(c.score * c.weight for c in components) / sum(c.weight for c in components))
    for c in components:
        c.weight = round(c.weight)

    priority = {"keywords": 0, "parsing": 1, "format": 2, "fit": 3}
    fixes = [f for c in sorted(components, key=lambda c: priority[c.key]) for f in c.findings]
    return AtsReport(
        total=total, components=components, matched=matched, missing_must=missing_must,
        missing_nice=missing_nice, fixes=fixes, pdf_checked=meta is not None, has_jd=has_jd,
    )
