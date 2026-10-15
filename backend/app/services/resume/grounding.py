"""
Is a piece of generated text supported by the candidate's library?

The writer, the bullet rewriter and the outreach generators all ask an LLM to stay within the library;
this module checks that they did. A text is unsupported when it contains

- a number the library never mentions,
- a skill (from the job description or the known tech vocabulary) the library never mentions,
- an employer-style claim ("at Google", "joined Stripe") naming an organisation the library never mentions.

The checks are deliberately conservative: when in doubt the generated text is replaced by the
candidate's own wording, which is always safe.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.services.resume import ats
from app.services.resume.schemas import JDAnalysis


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*\s*(?:%|k|x|\+)?", text.lower()))


def num_key(n: str) -> str:
    return re.sub(r"\s+", "", n)


# Tech terms that are also everyday words ("the rest of", "a swift reply", "spring 2024"). They only
# count as a skill claim when written capitalised somewhere other than the start of the text.
_EVERYDAY_TERMS = {"rest", "spring", "express", "swift", "rust", "combine", "flutter", "ruby", "go", "dart",
                   "git", "rag", "agile", "scrum", "spark", "lambda", "helm", "dart", "vite"}

# "at Google", "joined Meta", "at Acme Corp". "with"/"for" are left out: "with Product and Design" is a team.
_ORG_RE = re.compile(r"\b(?:at|joined|joining)\s+((?:[A-Z][\w&.'-]*)(?:\s+[A-Z][\w&.'-]*){0,3})")
# Capitalised words after those cues that are not organisations
_NOT_ORGS = {"I", "A", "An", "The", "My", "Our", "Your", "This", "That", "These", "Those", "Each", "Every",
             "All", "Over", "Under", "Up", "Both", "Several", "Multiple", "Many", "Most", "Some",
             "Scale", "Least", "Launch", "Peak", "Night", "Startup", "Speed", "Runtime", "Once"}


def _written_as_skill(term: str, text: str) -> bool:
    if not ats.term_in_text(term, text):
        return False
    if term.lower() not in _EVERYDAY_TERMS:
        return True
    for m in re.finditer(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE):
        if m.start() > 0 and m.group(0)[0].isupper():
            return True
    return False


def unsupported_skills(text: str, corpus: str, jd: JDAnalysis | None = None) -> list[str]:
    """Skills the text claims that the library never mentions."""
    terms = list(dict.fromkeys(
        [t.lower() for t in ((jd.must_have + jd.nice_to_have) if jd else [])] + ats.TECH_TERMS
    ))
    return [t for t in terms if _written_as_skill(t, text) and not ats.term_in_text(t, corpus)]


def unsupported_orgs(text: str, corpus: str, allowed: Iterable[str] = ()) -> list[str]:
    """Organisations named after "at"/"joined" that the library (or *allowed*) never mentions."""
    known = corpus.lower() + " " + " ".join(a.lower() for a in allowed if a)
    found = []
    for m in _ORG_RE.finditer(text):
        words = m.group(1).split()
        while words and words[0] in _NOT_ORGS:
            words = words[1:]
        name = " ".join(words).rstrip(".,'")
        if len(name) < 2 or name.lower() in known:
            continue
        # Partly known names ("AppFlow" for "AppFlow Studio") are fine; skills ("with Swift") are checked elsewhere
        if any(w.lower().rstrip(".,") in known for w in words if len(w) > 2):
            continue
        found.append(name)
    return found


def unsupported_numbers(text: str, corpus: str) -> list[str]:
    corpus_numbers = {num_key(n) for n in numbers(corpus)}
    return [n.strip() for n in numbers(text) if num_key(n) not in corpus_numbers]


def unsupported_claims(
    text: str, corpus: str, jd: JDAnalysis | None = None, allowed_orgs: Iterable[str] = (),
) -> list[str]:
    """Every claim in *text* that the library does not support, described for a warning."""
    return (
        [f"number {n}" for n in unsupported_numbers(text, corpus)]
        + [f"skill {s}" for s in unsupported_skills(text, corpus, jd)]
        + [f"organisation {o}" for o in unsupported_orgs(text, corpus, allowed_orgs)]
    )


def is_supported(text: str, corpus: str, jd: JDAnalysis | None = None, allowed_orgs: Iterable[str] = ()) -> bool:
    return not unsupported_claims(text, corpus, jd, allowed_orgs)
