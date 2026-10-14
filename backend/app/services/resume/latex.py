"""
Deterministic LaTeX rendering and compilation.

The LLM only produces structured data; this module turns it into LaTeX using a
fixed single-column, text-only template (the layout ATS parsers read best).
All user text is escaped, so model output can never inject LaTeX commands.
Compilation runs without shell escape and with restricted file access.
"""

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.services.resume.schemas import Profile
from app.utils.logging import get_logger

logger = get_logger(__name__)

_REPLACEMENTS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_CHAR_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "--", "\u2014": "---",
    "\u2022": "-", "\u00b7": "-", "\u2026": "...", "\u00a0": " ", "\u2192": "->", "\u2713": "",
    "\uf0b7": "-", "\u25cf": "-", "\u25aa": "-",
}


def esc(text: str) -> str:
    """Escape LaTeX specials and drop characters the template fonts can't render."""
    out = []
    for ch in str(text or ""):
        ch = _CHAR_MAP.get(ch, ch)
        for c in ch:
            if c in _REPLACEMENTS:
                out.append(_REPLACEMENTS[c])
            elif c == "\n" or c == "\t":
                out.append(" ")
            elif ord(c) < 0x250 or c in "-.'\"":
                out.append(c)
    return re.sub(r" {2,}", " ", "".join(out)).strip()


_PREAMBLE = r"""\documentclass[10pt,letterpaper]{article}
\usepackage[margin=0.6in]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}
\setlength{\tabcolsep}{0pt}
\newcommand{\sectionhead}[1]{\vspace{7pt}{\large\bfseries\MakeUppercase{#1}}\par\vspace{-4pt}\rule{\linewidth}{0.4pt}\par\vspace{2pt}}
\newenvironment{bullets}{\begin{itemize}\setlength{\itemsep}{1pt}\setlength{\parsep}{0pt}\setlength{\topsep}{2pt}\setlength{\leftmargin}{1.3em}}{\end{itemize}}
\begin{document}
"""


def _bullets(items: list[str]) -> str:
    items = [esc(b) for b in items if esc(b)]
    if not items:
        return ""
    return "\\begin{bullets}\n" + "\n".join(f"\\item {b}" for b in items) + "\n\\end{bullets}\n"


def _row(left: str, right: str, bold_left: bool = True, italic: bool = False) -> str:
    left, right = esc(left), esc(right)
    if not (left or right):
        return ""
    if bold_left:
        left = f"\\textbf{{{left}}}" if left else ""
    if italic:
        left = f"\\textit{{{left}}}" if left else ""
        right = f"\\textit{{{right}}}" if right else ""
    return f"{left}\\hfill {right}\\par\n"


def render_latex(p: Profile) -> str:
    out = [_PREAMBLE]

    contact = [esc(x) for x in (p.location, p.phone, p.email) if esc(x)]
    contact += [esc(l.replace("https://", "").replace("http://", "")) for l in p.links[:3]]
    out.append(f"\\begin{{center}}\n{{\\LARGE\\bfseries {esc(p.name) or 'Your Name'}}}\\\\[3pt]\n")
    out.append(" $|$ ".join(contact) + "\n\\end{center}\n\\vspace{-8pt}\n")

    if p.summary:
        out.append("\\sectionhead{Summary}\n" + esc(p.summary) + "\\par\n")

    if p.skills:
        out.append("\\sectionhead{Skills}\n")
        for group, items in p.skills.items():
            out.append(f"\\textbf{{{esc(group)}:}} {esc(', '.join(items))}\\par\n")

    if p.experience:
        out.append("\\sectionhead{Experience}\n")
        for exp in p.experience:
            out.append("\\vspace{3pt}\n" + _row(exp.company, exp.dates))
            out.append(_row(exp.title, exp.location, bold_left=False, italic=True))
            out.append(_bullets(exp.bullets))

    if p.projects:
        out.append("\\sectionhead{Projects}\n")
        for proj in p.projects:
            title = esc(proj.name) + (f" $|$ {esc(proj.tech)}" if proj.tech else "")
            out.append(f"\\vspace{{3pt}}\n\\textbf{{{title}}}\\par\n")
            out.append(_bullets(proj.bullets))

    if p.education:
        out.append("\\sectionhead{Education}\n")
        for edu in p.education:
            out.append(_row(edu.school, edu.dates))
            out.append(_row(edu.degree, edu.location, bold_left=False, italic=True))
            if edu.details:
                out.append(esc(edu.details) + "\\par\n")

    if p.certifications:
        out.append("\\sectionhead{Certifications}\n" + _bullets(p.certifications))
    if p.achievements:
        out.append("\\sectionhead{Achievements}\n" + _bullets(p.achievements))

    out.append("\\end{document}\n")
    return "".join(out)


def profile_plain_text(p: Profile) -> str:
    """Plain-text rendering used to score when no PDF could be compiled."""
    lines = [p.name, " | ".join(x for x in (p.location, p.phone, p.email, *p.links) if x), ""]
    if p.summary:
        lines += ["SUMMARY", p.summary, ""]
    if p.skills:
        lines.append("SKILLS")
        lines += [f"{g}: {', '.join(s)}" for g, s in p.skills.items()] + [""]
    if p.experience:
        lines.append("EXPERIENCE")
        for e in p.experience:
            lines += [f"{e.company} {e.dates}", f"{e.title} {e.location}"] + [f"- {b}" for b in e.bullets]
        lines.append("")
    if p.projects:
        lines.append("PROJECTS")
        for pr in p.projects:
            lines += [f"{pr.name} | {pr.tech}"] + [f"- {b}" for b in pr.bullets]
        lines.append("")
    if p.education:
        lines.append("EDUCATION")
        for ed in p.education:
            lines += [f"{ed.school} {ed.dates}", f"{ed.degree} {ed.location}", ed.details]
        lines.append("")
    if p.certifications:
        lines += ["CERTIFICATIONS"] + [f"- {c}" for c in p.certifications] + [""]
    if p.achievements:
        lines += ["ACHIEVEMENTS"] + [f"- {a}" for a in p.achievements]
    return "\n".join(lines)


def compiler_available() -> bool:
    return shutil.which("pdflatex") is not None


def _compile_sync(tex: str) -> tuple[bytes | None, str]:
    compiler = shutil.which("pdflatex")
    if not compiler:
        return None, "pdflatex is not installed on the server."
    with tempfile.TemporaryDirectory(prefix="resume_") as tmp:
        (Path(tmp) / "resume.tex").write_text(tex, encoding="utf-8")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": tmp,
            "TEXMFOUTPUT": tmp,
            "openin_any": "p",       # paranoid file access: no reads outside cwd/TEXMF
            "openout_any": "p",
        }
        try:
            proc = subprocess.run(
                [compiler, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "resume.tex"],
                cwd=tmp, env=env, capture_output=True, timeout=90, text=True, errors="replace",
            )
        except subprocess.TimeoutExpired:
            return None, "LaTeX compilation timed out."
        pdf_path = Path(tmp) / "resume.pdf"
        if proc.returncode != 0 or not pdf_path.exists():
            tail = "\n".join(proc.stdout.splitlines()[-15:])
            logger.warning("pdflatex failed:\n%s", tail)
            return None, f"LaTeX compilation failed:\n{tail}"
        return pdf_path.read_bytes(), ""


_compile_slots = asyncio.Semaphore(2)   # pdflatex needs real RAM/CPU; don't let many users compile at once


async def compile_pdf(tex: str) -> tuple[bytes | None, str]:
    """Compile LaTeX to PDF in a worker thread. Returns (pdf_bytes | None, error)."""
    async with _compile_slots:
        return await asyncio.to_thread(_compile_sync, tex)


def unsupported_characters(p: Profile) -> list[str]:
    """Characters esc() has to drop because the template's Latin fonts cannot render them."""
    text = " ".join([
        p.name, p.email, p.phone, p.location, p.summary, *p.links, *p.certifications, *p.achievements,
        *(f"{e.company} {e.title} {e.location} {e.dates} {' '.join(e.bullets)}" for e in p.experience),
        *(f"{x.name} {x.tech} {' '.join(x.bullets)}" for x in p.projects),
        *(f"{e.school} {e.degree} {e.location} {e.details}" for e in p.education),
        *(f"{g} {' '.join(s)}" for g, s in p.skills.items()),
    ])
    return sorted({c for c in text if ord(c) >= 0x250 and c not in _CHAR_MAP and c.isalpha()})
