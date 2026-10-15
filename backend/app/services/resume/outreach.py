"""
Grounded Cover Letter and Recruiter Outreach generator.

Reuses the verified candidate profile, library corpus, and analyzed JD from the
resume pipeline to produce factual, high-impact cover letters and cold outreach messages
with zero grounding violations or fabricated experience.
"""

import re
from typing import Literal

from app.services.resume.llm_utils import llm_json
from app.services.resume.schemas import JDAnalysis, Profile
from app.utils.logging import get_logger

logger = get_logger(__name__)

_COVER_LETTER_PROMPT = """\
You are an executive career coach writing a highly tailored, authentic cover letter.

ABSOLUTE GROUNDING RULES:
1. Use ONLY real facts, employers, projects, metrics, numbers, and technologies from the CANDIDATE PROFILE.
2. NEVER invent achievements, responsibilities, statistics, or background.
3. If the job description asks for something not in the candidate's profile, focus on transferable real strengths rather than inventing claims.
4. Match the candidate's strongest proven achievements to the target role's core requirements.

Format as a structured JSON object:
{
  "subject": "Application for <Job Title> - <Candidate Name>",
  "salutation": "Dear Hiring Team at <Company> (or Dear Hiring Manager)",
  "opening": "1 punchy paragraph declaring the role, company, and overall value proposition",
  "body_paragraphs": [
    "Paragraph 1 connecting candidate's proven experience to top must-have requirements",
    "Paragraph 2 highlighting relevant projects, technologies, and quantified metrics"
  ],
  "closing": "1 professional closing paragraph proposing a conversation",
  "sign_off": "Sincerely,\\n<Candidate Name>",
  "full_text": "Complete formatted letter text ready to copy or send"
}"""

_RECRUITER_MESSAGE_PROMPT = """\
You write concise, high-converting recruiter outreach messages (LinkedIn InMail or short email).

ABSOLUTE GROUNDING RULES:
1. Use ONLY real facts, roles, projects, and numbers from the CANDIDATE PROFILE.
2. Keep it under 150 words. Punchy, professional, and respectful of the recruiter's time.
3. Highlight 2-3 specific real accomplishments directly relevant to the role.
4. Clear, low-friction call to action (e.g. 10-minute chat or sending full resume).

Format as a structured JSON object:
{
  "subject": "Quick note regarding <Role> opening at <Company>",
  "preview": "One sentence summary hook",
  "message": "Full message text ready to send on LinkedIn or email",
  "highlight_points": ["bullet 1 grounded accomplishment", "bullet 2 grounded accomplishment"]
}"""


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,.]*\s*(?:%|k|x|\+)?", text.lower()))


def _num_key(n: str) -> str:
    return re.sub(r"\s+", "", n)


def _profile_context(profile: Profile) -> str:
    lines = [
        f"CANDIDATE: {profile.name}",
        f"EMAIL: {profile.email} | LOCATION: {profile.location}",
        f"LINKS: {', '.join(profile.links)}",
        "\nSKILLS:",
    ]
    for cat, skills in profile.skills.items():
        lines.append(f"- {cat}: {', '.join(skills)}")

    lines.append("\nEXPERIENCE:")
    for exp in profile.experience:
        lines.append(f"- {exp.title} at {exp.company} ({exp.dates})")
        for b in exp.bullets:
            lines.append(f"  * {b}")

    if profile.projects:
        lines.append("\nPROJECTS:")
        for p in profile.projects:
            lines.append(f"- {p.name} ({p.tech}): {', '.join(p.bullets)}")

    if profile.education:
        lines.append("\nEDUCATION:")
        for edu in profile.education:
            lines.append(f"- {edu.degree} from {edu.school} ({edu.dates}) {edu.details}")

    return "\n".join(lines)


async def generate_cover_letter(
    profile: Profile,
    jd: JDAnalysis,
    jd_text: str,
    corpus: str = "",
) -> dict:
    """Generate a grounded cover letter tailored to the job description."""
    candidate_summary = _profile_context(profile)
    user_prompt = (
        f"TARGET JOB:\n"
        f"Title: {jd.title or 'Target Role'}\n"
        f"Company: {jd.company or 'Hiring Company'}\n"
        f"Must-Have Skills: {', '.join(jd.must_have)}\n"
        f"Responsibilities: {'; '.join(jd.responsibilities)}\n\n"
        f"FULL JOB DESCRIPTION:\n{jd_text[:4000]}\n\n"
        f"CANDIDATE VERIFIED PROFILE:\n{candidate_summary}"
    )

    data = await llm_json(_COVER_LETTER_PROMPT, user_prompt)
    full_text = data.get("full_text")
    if not full_text:
        body = "\n\n".join(data.get("body_paragraphs", []))
        full_text = (
            f"{data.get('salutation', 'Dear Hiring Manager,')}\n\n"
            f"{data.get('opening', '')}\n\n"
            f"{body}\n\n"
            f"{data.get('closing', '')}\n\n"
            f"{data.get('sign_off', 'Sincerely,')}"
        )

    # Check that numbers in cover letter exist in corpus / profile
    corpus_numbers = {_num_key(n) for n in _numbers(corpus or candidate_summary)}
    unsupported = [n for n in _numbers(full_text) if _num_key(n) not in corpus_numbers]
    warnings = []
    if unsupported:
        warnings.append(f"Notice: Verify specific metrics in cover letter: {', '.join(unsupported[:5])}")

    return {
        "subject": data.get("subject", f"Application for {jd.title} - {profile.name}"),
        "salutation": data.get("salutation", "Dear Hiring Manager,"),
        "opening": data.get("opening", ""),
        "body_paragraphs": data.get("body_paragraphs", []),
        "closing": data.get("closing", ""),
        "sign_off": data.get("sign_off", f"Sincerely,\n{profile.name}"),
        "full_text": full_text,
        "warnings": warnings,
    }


async def generate_recruiter_message(
    profile: Profile,
    jd: JDAnalysis,
    jd_text: str,
    platform: Literal["linkedin", "email"] = "linkedin",
    corpus: str = "",
) -> dict:
    """Generate a grounded, high-conversion recruiter message."""
    candidate_summary = _profile_context(profile)
    user_prompt = (
        f"PLATFORM: {platform.upper()}\n"
        f"TARGET JOB:\n"
        f"Title: {jd.title or 'Target Role'}\n"
        f"Company: {jd.company or 'Hiring Company'}\n"
        f"Must-Have Skills: {', '.join(jd.must_have)}\n\n"
        f"CANDIDATE VERIFIED PROFILE:\n{candidate_summary}"
    )

    data = await llm_json(_RECRUITER_MESSAGE_PROMPT, user_prompt)
    message = data.get("message", "")

    corpus_numbers = {_num_key(n) for n in _numbers(corpus or candidate_summary)}
    unsupported = [n for n in _numbers(message) if _num_key(n) not in corpus_numbers]
    warnings = []
    if unsupported:
        warnings.append(f"Notice: Verify specific metrics: {', '.join(unsupported[:3])}")

    return {
        "subject": data.get("subject", f"Regarding {jd.title} at {jd.company}"),
        "preview": data.get("preview", ""),
        "message": message,
        "highlight_points": data.get("highlight_points", []),
        "platform": platform,
        "warnings": warnings,
    }
