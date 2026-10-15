"""
Deterministic LaTeX rendering and compilation.

The LLM only produces structured data; this module turns it into LaTeX using a
fixed single-column, text-only template (the layout ATS parsers read best).
The built-in templates share that rule and differ only in spacing and section order.
All user text is escaped, so model output can never inject LaTeX commands, and the
layout options are whitelisted values (see RenderOptions), never free text.

A user may instead supply the preamble of their own LaTeX resume (a "base template"): the content is then
written with standard \section* and itemize, so the template's own styling of those applies. Such a
preamble is checked by check_preamble() (no file access, no shell, no catcode tricks) when it is uploaded
and again before every render.
Compilation runs without shell escape and with restricted file access.
"""

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.services.resume.schemas import Profile, RenderOptions
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


# Look of each template: space before a section, section title size, gap between bullets, name size.
_STYLES = {
    "classic": {"before": "7pt", "title": r"\large", "item": "1pt", "name": r"\LARGE"},
    "compact": {"before": "4pt", "title": r"\normalsize", "item": "0pt", "name": r"\Large"},
    "skills_first": {"before": "7pt", "title": r"\large", "item": "1pt", "name": r"\LARGE"},
    "student": {"before": "7pt", "title": r"\large", "item": "1pt", "name": r"\LARGE"},
}

# Section order per template; every template uses the same standard headings an ATS looks for.
_ORDERS = {
    "classic": ["summary", "skills", "experience", "projects", "education", "certifications", "achievements"],
    "compact": ["summary", "skills", "experience", "projects", "education", "certifications", "achievements"],
    "skills_first": ["skills", "summary", "experience", "projects", "education", "certifications", "achievements"],
    "student": ["education", "skills", "projects", "experience", "certifications", "achievements", "summary"],
}

_PREAMBLE = r"""\documentclass[@FONT@pt,letterpaper]{article}
\usepackage[margin=@MARGIN@in]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}
\setlength{\tabcolsep}{0pt}
\newcommand{\sectionhead}[1]{\vspace{@BEFORE@}{@TITLE@\bfseries\MakeUppercase{#1}}\par\vspace{-4pt}\rule{\linewidth}{0.4pt}\par\vspace{2pt}}
\newenvironment{bullets}{\begin{itemize}\setlength{\itemsep}{@ITEM@}\setlength{\parsep}{0pt}\setlength{\topsep}{2pt}\setlength{\leftmargin}{1.3em}}{\end{itemize}}
\begin{document}
"""


def _preamble(opts: RenderOptions) -> str:
    style = _STYLES[opts.template]
    text = (
        _PREAMBLE.replace("@FONT@", str(opts.font_pt))
        .replace("@MARGIN@", str(opts.margin_in))
        .replace("@BEFORE@", style["before"])
        .replace("@TITLE@", style["title"])
        .replace("@ITEM@", style["item"])
    )
    if opts.font == "sans":
        text = text.replace("\\usepackage{lmodern}\n", "\\usepackage{lmodern}\n\\renewcommand{\\familydefault}{\\sfdefault}\n")
    return text


# ── Base templates (the user's own LaTeX preamble) ──────────────────────────

MAX_PREAMBLE_CHARS = 20000

# Anything that reads or writes files, runs programs, or rewrites how TeX reads input (which could be used to
# smuggle the other commands past this check). Compilation also runs with -no-shell-escape and openin_any=p.
_FORBIDDEN = re.compile(
    r"\\(include|includeonly|InputIfFileExists|IfFileExists|openin|openout|read|readline|write|"
    r"immediate|write18|directlua|luaexec|latelua|catcode|csname|scantokens|lowercase|uppercase|newread|"
    r"newwrite|special|pdfobj|pdffiledump|pdfximage|includegraphics|endinput|everyjob|everypar|output)(?![A-Za-z])"
    r"|\^\^|\\usepackage(\[[^\]]*\])?\{[^}]*\b(shellesc|pythontex|minted|luacode|bashful|catchfile|verbatim)\b",
)


def check_preamble(source: str) -> str:
    """The safe preamble of an uploaded .tex (everything before \\begin{document}); raises ValueError if unusable."""
    text = source.replace("\r\n", "\n")
    head = text.split("\\begin{document}", 1)[0]
    head = re.sub(r"(?<!\\)%.*", "", head)            # comments can't hide anything from the check
    if "\\documentclass" not in head:
        raise ValueError("This doesn't look like a LaTeX resume: there is no \\documentclass line.")
    if len(head) > MAX_PREAMBLE_CHARS:
        raise ValueError("The template's preamble is too long (20,000 characters at most).")
    # \input of a TeX library file by plain name (e.g. Jake's resume: \input{glyphtounicode}) is fine;
    # anything with a path, an extension or no braces is not
    for target in re.findall(r"\\input(?![A-Za-z])\s*(\{[^}]*\}|\S+)", head):
        if not re.fullmatch(r"\{[A-Za-z0-9_-]{1,40}\}", target):
            raise ValueError(f"The template uses \\input{target}; only TeX's own files can be input here.")
    bad = _FORBIDDEN.search(head)
    if bad:
        raise ValueError(
            f"The template uses {bad.group(0).strip()}, which isn't allowed here (file access, shell or catcode "
            "tricks). Remove it and upload again."
        )
    return head.strip() + "\n"


def _bullets(items: list[str], env: str = "bullets") -> str:
    items = [esc(b) for b in items if esc(b)]
    if not items:
        return ""
    return f"\\begin{{{env}}}\n" + "\n".join(f"\\item {b}" for b in items) + f"\n\\end{{{env}}}\n"


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


def _sections(p: Profile, head=None, env: str = "bullets") -> dict[str, str]:
    """Each section's LaTeX, keyed by name; an empty section is an empty string.
    ``head`` makes a section title (built-in macro by default, \\section* for base templates)."""
    head = head or (lambda title: f"\\sectionhead{{{title}}}\n")
    sections: dict[str, str] = {}

    def _bullets(items: list[str]) -> str:   # noqa: F811 - the list environment depends on the template
        return _bullet_list(items, env)

    if p.summary:
        sections["summary"] = head("Summary") + esc(p.summary) + "\\par\n"

    if p.skills:
        text = head("Skills")
        for group, items in p.skills.items():
            text += f"\\textbf{{{esc(group)}:}} {esc(', '.join(items))}\\par\n"
        sections["skills"] = text

    if p.experience:
        text = head("Experience")
        for exp in p.experience:
            text += "\\vspace{3pt}\n" + _row(exp.company, exp.dates)
            text += _row(exp.title, exp.location, bold_left=False, italic=True)
            text += _bullets(exp.bullets)
        sections["experience"] = text

    if p.projects:
        text = head("Projects")
        for proj in p.projects:
            title = esc(proj.name) + (f" $|$ {esc(proj.tech)}" if proj.tech else "")
            text += f"\\vspace{{3pt}}\n\\textbf{{{title}}}\\par\n"
            text += _bullets(proj.bullets)
        sections["projects"] = text

    if p.education:
        text = head("Education")
        for edu in p.education:
            text += _row(edu.school, edu.dates)
            text += _row(edu.degree, edu.location, bold_left=False, italic=True)
            if edu.details:
                text += esc(edu.details) + "\\par\n"
        sections["education"] = text

    if p.certifications:
        sections["certifications"] = head("Certifications") + _bullets(p.certifications)
    if p.achievements:
        sections["achievements"] = head("Achievements") + _bullets(p.achievements)
    return sections


_bullet_list = _bullets


def section_order(opts: RenderOptions) -> list[str]:
    """The chosen order (e.g. copied from a PDF), with any section it leaves out kept in the template's order."""
    base = _ORDERS[opts.template]
    if not opts.section_order:
        return base
    return list(dict.fromkeys([*opts.section_order, *base]))


def render_latex(p: Profile, options: RenderOptions | None = None) -> str:
    opts = options or RenderOptions()
    style = _STYLES[opts.template]
    contact = [esc(x) for x in (p.location, p.phone, p.email) if esc(x)]
    contact += [esc(l.replace("https://", "").replace("http://", "")) for l in p.links[:3]]

    if opts.preamble:
        # The user's own template: their preamble, standard commands so its styling of them applies
        out = [check_preamble(opts.preamble), "\\begin{document}\n"]
        out.append(f"\\begin{{center}}\n{{\\Large\\bfseries {esc(p.name) or 'Your Name'}}}\\\\[3pt]\n")
        out.append(" $|$ ".join(contact) + "\n\\end{center}\n")
        sections = _sections(p, head=lambda title: f"\\section*{{{title}}}\n", env="itemize")
    else:
        out = [_preamble(opts)]
        out.append(f"\\begin{{center}}\n{{{style['name']}\\bfseries {esc(p.name) or 'Your Name'}}}\\\\[3pt]\n")
        out.append(" $|$ ".join(contact) + "\n\\end{center}\n\\vspace{-8pt}\n")
        sections = _sections(p)

    out.extend(sections[name] for name in section_order(opts) if name in sections)
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
