"""Base templates (a user's own LaTeX preamble or the look of their PDF) and the options they turn into."""

import pymupdf
import pytest

from app.services.resume.latex import check_preamble, render_latex, section_order
from app.services.resume.layouts import layout_from_pdf
from app.services.resume.schemas import Profile, RenderOptions

JAKE_STYLE = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{enumitem}
\input{glyphtounicode}
\pdfgentounicode=1
% section titles in small caps with a rule
\titleformat{\section}{\vspace{-4pt}\scshape\raggedright\large}{}{0em}{}[\titlerule \vspace{-5pt}]
\setlist[itemize]{leftmargin=0.15in, label={--}}
\begin{document}
\section{Old content that is ignored}
\end{document}
"""

PROFILE = Profile(
    name="Ada Lovelace", email="ada@example.com", summary="Analyst.",
    skills={"Languages": ["Python"]},
    experience=[{"company": "Engines Ltd", "title": "Analyst", "dates": "1843", "bullets": ["Wrote the first program."]}],
    education=[{"school": "Home", "degree": "Mathematics", "dates": "1830"}],
)


def test_a_normal_template_preamble_is_accepted_without_its_body_or_comments():
    head = check_preamble(JAKE_STYLE)
    assert head.startswith(r"\documentclass") and r"\titleformat{\section}" in head
    assert "Old content" not in head and "section titles in small caps" not in head


@pytest.mark.parametrize("bad", [
    r"\input{/etc/passwd}",
    r"\input{../secret}",
    r"\input secret.txt",
    r"\immediate\write18{rm -rf /}",
    r"\def\x{^^5cinput}",
    r"\csname input\endcsname{secret}",
    r"\usepackage{minted}",
    r"\openin1=secret.txt",
    r"\catcode`\X=0",
])
def test_templates_that_could_reach_files_or_the_shell_are_refused(bad):
    with pytest.raises(ValueError):
        check_preamble("\\documentclass{article}\n" + bad + "\n\\begin{document}\\end{document}")


def test_a_file_without_a_documentclass_is_refused():
    with pytest.raises(ValueError, match="documentclass"):
        check_preamble(r"\usepackage{geometry}")


def test_content_is_written_with_standard_commands_inside_the_users_template():
    tex = render_latex(PROFILE, RenderOptions(preamble=check_preamble(JAKE_STYLE)))
    assert tex.startswith(r"\documentclass[letterpaper,11pt]{article}")
    assert r"\section*{Experience}" in tex and r"\begin{itemize}" in tex
    assert r"\sectionhead" not in tex and "Old content" not in tex
    assert tex.count(r"\begin{document}") == 1 and tex.rstrip().endswith(r"\end{document}")


def test_a_preamble_is_checked_again_at_render_time():
    with pytest.raises(ValueError):
        render_latex(PROFILE, RenderOptions(preamble="\\documentclass{article}\n\\input{/tmp/x}\n"))


def test_section_order_and_sans_font():
    opts = RenderOptions(section_order=["education", "experience"], font="sans")
    assert section_order(opts)[:2] == ["education", "experience"] and "skills" in section_order(opts)
    tex = render_latex(PROFILE, opts)
    assert tex.index(r"\sectionhead{Education}") < tex.index(r"\sectionhead{Experience}") < tex.index(r"\sectionhead{Skills}")
    assert r"\renewcommand{\familydefault}{\sfdefault}" in tex


def make_pdf(font: str, size: float, margin_pt: float, headings: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 60
    for heading in headings:
        page.insert_text((margin_pt, y), heading.upper(), fontname=font, fontsize=size + 2)
        y += 20
        for _ in range(4):
            page.insert_text((margin_pt, y), "Delivered a measurable result for the team over the quarter.", fontname=font, fontsize=size)
            y += 15
        y += 10
    data = doc.tobytes()
    doc.close()
    return data


def test_a_pdf_resume_gives_matching_layout_options():
    pdf = make_pdf("helv", 11, 54, ["Education", "Experience", "Skills"])
    options, notes = layout_from_pdf(pdf)
    assert options.font_pt == 11 and options.margin_in == 0.75 and options.font == "sans"
    assert options.section_order == ["education", "experience", "skills"] and options.template == "student"
    assert any("Section order" in n for n in notes)


def test_a_serif_pdf_with_narrow_margins():
    options, _ = layout_from_pdf(make_pdf("tiro", 10, 36, ["Summary", "Experience"]))
    assert options.font == "serif" and options.font_pt == 10 and options.margin_in == 0.5
    assert options.section_order == ["summary", "experience"]
