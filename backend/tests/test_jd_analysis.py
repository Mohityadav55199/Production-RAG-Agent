"""Job-description analysis: the LLM result is cached (bounded, copied); the keyword fallback is not."""

import asyncio

import pytest

from app.services.resume import agents, ats

IOS_JD = (
    "Pulse Fitness is looking for a passionate iOS Developer skilled in Swift, SwiftUI, and UIKit. You will build "
    "high-performance mobile animations, implement offline data synchronization with CoreData, and maintain fast "
    "CI/CD builds with Xcode and TestFlight."
)


@pytest.fixture(autouse=True)
def _empty_cache():
    agents.clear_jd_cache()
    yield
    agents.clear_jd_cache()


def test_fallback_understands_mobile_postings():
    jd = ats.fallback_jd_analysis(IOS_JD)
    for term in ("ios", "swift", "swiftui", "uikit", "core data", "xcode", "testflight", "ci/cd"):
        assert term in jd.must_have, term
    assert jd.must_have[0] == "ios"            # ordered by where the posting mentions them


def test_llm_analysis_is_cached_and_callers_get_copies(monkeypatch):
    calls = []

    async def fake_llm(system, user):
        calls.append(user)
        return {"title": "iOS Developer", "must_have": ["Swift"], "nice_to_have": []}

    monkeypatch.setattr(agents, "llm_json", fake_llm)
    first = asyncio.run(agents.analyze_jd(IOS_JD))
    first.must_have.append("changed by the caller")
    second = asyncio.run(agents.analyze_jd(IOS_JD))
    assert len(calls) == 1
    assert "changed by the caller" not in second.must_have


def test_fallback_result_is_not_cached(monkeypatch):
    calls = []

    async def failing_llm(system, user):
        calls.append(user)
        raise RuntimeError("rate limited")

    monkeypatch.setattr(agents, "llm_json", failing_llm)
    asyncio.run(agents.analyze_jd(IOS_JD))
    asyncio.run(agents.analyze_jd(IOS_JD))
    assert len(calls) == 2                      # the second paste tries the LLM again


def test_cache_is_bounded(monkeypatch):
    async def fake_llm(system, user):
        return {"must_have": ["Python"]}

    monkeypatch.setattr(agents, "llm_json", fake_llm)
    monkeypatch.setattr(agents, "_JD_CACHE_SIZE", 3)
    for i in range(5):
        asyncio.run(agents.analyze_jd(f"Python developer wanted, posting number {i}."))
    assert len(agents._JD_CACHE) == 3
