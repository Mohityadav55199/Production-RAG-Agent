"""Which chat models the factory builds: primary model, fallback chain and gpt-oss reasoning settings."""

import pytest

from app.config import get_settings
from app.services import llm_factory


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(s, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(s, "PRIMARY_LLM_PROVIDER", "groq")
    monkeypatch.setattr(s, "PRIMARY_LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(s, "GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setattr(s, "FALLBACK_LLM_MODELS", "openai/gpt-oss-20b, gemini:gemini-2.5-flash")
    monkeypatch.setattr(s, "ENABLE_LLM_FALLBACK", True)
    monkeypatch.setattr(s, "GROQ_REASONING_EFFORT", "low")
    return s


def _models(llm) -> list[str]:
    runnables = [llm.runnable, *llm.fallbacks] if hasattr(llm, "fallbacks") else [llm]
    return [r.bound.model_name for r in runnables]


def test_primary_model_setting_is_used(settings, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_LLM_MODEL", "openai/gpt-oss-20b")
    monkeypatch.setattr(settings, "FALLBACK_LLM_MODELS", "")
    monkeypatch.setattr(settings, "ENABLE_LLM_FALLBACK", False)
    assert _models(llm_factory.get_configured_llm()) == ["openai/gpt-oss-20b"]


def test_fallback_chain_skips_providers_without_a_key(settings):
    # No Google key: the gemini entry is dropped rather than failing at request time
    assert _models(llm_factory.get_configured_llm()) == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_fallback_chain_includes_gemini_when_keyed(settings, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "g_test")
    llm = llm_factory.get_configured_llm()
    assert len(llm.fallbacks) == 2
    assert llm.fallbacks[1].bound.model == "gemini-2.5-flash"


def test_reasoning_effort_only_for_gpt_oss(settings):
    oss = llm_factory.build_chat_model("groq", "openai/gpt-oss-120b", "gsk_test")
    other = llm_factory.build_chat_model("groq", "qwen/qwen3.6-27b", "gsk_test")
    assert oss.reasoning_effort == "low"
    assert other.reasoning_effort is None


def test_auto_provider_picks_the_configured_key(settings, monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_LLM_PROVIDER", "auto")
    monkeypatch.setattr(settings, "ENABLE_LLM_FALLBACK", False)
    assert _models(llm_factory.get_configured_llm()) == ["openai/gpt-oss-120b"]


def test_no_retired_groq_models_in_defaults():
    from app.config import Settings

    fields = Settings.model_fields
    defaults = " ".join(
        str(fields[name].default)
        for name in ("PRIMARY_LLM_MODEL", "GROQ_MODEL", "FALLBACK_LLM_MODELS", "FALLBACK_LLM_MODEL", "QUERY_REWRITE_MODEL")
    )
    assert "llama-3.3-70b-versatile" not in defaults
    assert "llama-3.1-8b-instant" not in defaults
