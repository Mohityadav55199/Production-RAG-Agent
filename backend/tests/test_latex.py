import asyncio

import pytest

from app.services.resume import latex
from app.services.resume.schemas import Profile
from tests.sample_data import library_profile


def test_special_characters_are_escaped():
    assert latex.esc("R&D 50% $5 #1 a_b {x}") == r"R\&D 50\% \$5 \#1 a\_b \{x\}"


def test_commands_in_user_text_are_inert():
    # A hostile resume or model output must never become a LaTeX command
    out = latex.esc(r"\immediate\write18{touch /tmp/pwned}\input{/etc/passwd}")
    assert "\\immediate" not in out.replace(r"\textbackslash{}immediate", "")
    assert r"\textbackslash{}" in out
    assert r"\{" in out and r"\}" in out


def test_typographic_characters_are_normalised():
    assert latex.esc("“quoted” – dash • bullet") == '"quoted" -- dash - bullet'


def test_render_contains_escaped_content_and_sections():
    p = library_profile()
    p.experience[0].company = "Acme & Sons"
    tex = latex.render_latex(p)
    assert r"Acme \& Sons" in tex
    for heading in ("Summary", "Skills", "Experience", "Projects", "Education"):
        assert heading in tex
    assert tex.rstrip().endswith(r"\end{document}")


def test_render_never_emits_unescaped_input_commands():
    p = Profile(name=r"\input{/etc/passwd}", summary=r"\write18{x}")
    tex = latex.render_latex(p)
    assert r"\input{/etc/passwd}" not in tex
    assert r"\write18" not in tex.replace(r"\textbackslash{}write18", "")


def test_unsupported_characters_are_reported_not_silently_lost():
    p = library_profile()
    p.name = "Asha वर्मा"   # Devanagari
    assert latex.unsupported_characters(p)
    assert not latex.unsupported_characters(library_profile())


def test_plain_text_rendering_has_headings_and_bullets():
    text = latex.profile_plain_text(library_profile())
    assert "EXPERIENCE" in text and "- Built REST APIs" in text


@pytest.mark.skipif(not latex.compiler_available(), reason="pdflatex is not installed")
def test_compiles_to_a_real_pdf():
    pdf, error = asyncio.run(latex.compile_pdf(latex.render_latex(library_profile())))
    assert error == ""
    assert pdf and pdf.startswith(b"%PDF")


@pytest.mark.skipif(not latex.compiler_available(), reason="pdflatex is not installed")
def test_hostile_raw_latex_is_rejected_by_the_sandbox(tmp_path):
    marker = tmp_path / "pwned"
    evil = latex.render_latex(library_profile()).replace(
        "Asha Verma", rf"\immediate\write18{{touch {marker}}}\input{{/etc/passwd}}"
    )
    pdf, _ = asyncio.run(latex.compile_pdf(evil))
    assert pdf is None
    assert not marker.exists()
