"""Realistic sample resume data shared by the resume tests."""

from app.services.resume.schemas import Profile

LIBRARY_PROFILE = {
    "name": "Asha Verma",
    "email": "asha@example.com",
    "phone": "+91 98765 43210",
    "location": "Pune, India",
    "links": ["https://github.com/asha"],
    "summary": "Full stack developer.",
    "skills": {
        "Languages": ["Python", "JavaScript"],
        "Frameworks": ["FastAPI", "React"],
        "Tools": ["Docker", "PostgreSQL", "Git"],
    },
    "experience": [{
        "company": "Acme",
        "title": "Software Engineer",
        "location": "Pune",
        "dates": "Jun 2023 - Present",
        "bullets": [
            "Built REST APIs with FastAPI serving 50k requests/day and cutting latency by 35%.",
            "Developed a React dashboard used by 200+ analysts, reducing report time by 40%.",
            "Deployed services with Docker and CI/CD, shrinking release time from 2 hours to 15 minutes.",
            "Implemented PostgreSQL schemas and unit tests with pytest reaching 85% coverage.",
        ],
    }],
    "projects": [{
        "name": "RAG Agent",
        "tech": "FastAPI, Qdrant",
        "bullets": ["Built a RAG app indexing 200 files with Gemini embeddings and Groq LLMs."],
    }],
    "education": [{
        "school": "Pune University", "degree": "B.Tech CS", "dates": "2019 - 2023",
        "location": "Pune", "details": "CGPA 8.7",
    }],
    "certifications": ["AWS Cloud Practitioner"],
}

LIBRARY_CORPUS = (
    "Asha Verma Python FastAPI React Docker PostgreSQL REST APIs CI/CD pytest Git JavaScript "
    "Built REST APIs with FastAPI serving 50k requests/day and cutting latency by 35%. "
    "Developed a React dashboard used by 200+ analysts, reducing report time by 40%. "
    "Deployed services with Docker and CI/CD, shrinking release time from 2 hours to 15 minutes. "
    "Implemented PostgreSQL schemas and unit tests with pytest reaching 85% coverage. "
    "Built a RAG app indexing 200 files with Gemini embeddings and Groq LLMs."
)


def library_profile() -> Profile:
    return Profile.model_validate(LIBRARY_PROFILE)
