"""Structured data shapes used across the resume pipeline."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


class _Tolerant(BaseModel):
    """LLM output is messy: ignore unknown keys and coerce None -> empty."""

    model_config = ConfigDict(extra="ignore")


class Experience(_Tolerant):
    company: str = ""
    title: str = ""
    location: str = ""
    dates: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("company", "title", "location", "dates", mode="before")
    @classmethod
    def _str(cls, v):
        return _clean(v)

    @field_validator("bullets", mode="before")
    @classmethod
    def _bullets(cls, v):
        return [_clean(b) for b in (v or []) if _clean(b)]


class Project(_Tolerant):
    name: str = ""
    tech: str = ""
    link: str = ""
    bullets: list[str] = Field(default_factory=list)

    @field_validator("name", "tech", "link", mode="before")
    @classmethod
    def _str(cls, v):
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        return _clean(v)

    @field_validator("bullets", mode="before")
    @classmethod
    def _bullets(cls, v):
        return [_clean(b) for b in (v or []) if _clean(b)]


class Education(_Tolerant):
    school: str = ""
    degree: str = ""
    dates: str = ""
    location: str = ""
    details: str = ""

    @field_validator("school", "degree", "dates", "location", "details", mode="before")
    @classmethod
    def _str(cls, v):
        return _clean(v)


class Profile(_Tolerant):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: dict[str, list[str]] = Field(default_factory=dict)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)

    @field_validator("name", "email", "phone", "location", "summary", mode="before")
    @classmethod
    def _str(cls, v):
        return _clean(v)

    @field_validator("links", "certifications", "achievements", mode="before")
    @classmethod
    def _str_list(cls, v):
        return [_clean(x) for x in (v or []) if _clean(x)]

    @field_validator("skills", mode="before")
    @classmethod
    def _skills(cls, v):
        if isinstance(v, list):  # flat list -> one group
            v = {"Skills": v}
        out: dict[str, list[str]] = {}
        for group, items in (v or {}).items():
            if isinstance(items, str):
                items = [s for s in items.split(",")]
            cleaned = [_clean(i) for i in (items or []) if _clean(i)]
            if cleaned:
                out[_clean(group) or "Skills"] = cleaned
        return out


class RenderOptions(BaseModel):
    """Layout choices for the generated PDF. Every field is a fixed whitelist, so these values can be put into
    LaTeX without escaping and a client can never inject commands through them."""

    template: Literal["classic", "compact", "skills_first", "student"] = "classic"
    font_pt: Literal[10, 11, 12] = 10
    margin_in: Literal[0.5, 0.6, 0.75, 1.0] = 0.6


class JDAnalysis(_Tolerant):
    title: str = ""
    company: str = ""
    seniority: str = ""
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)

    @field_validator("title", "company", "seniority", mode="before")
    @classmethod
    def _str(cls, v):
        return _clean(v)

    @field_validator("must_have", "nice_to_have", "responsibilities", mode="before")
    @classmethod
    def _list(cls, v):
        return [_clean(x) for x in (v or []) if _clean(x)]
