"""The answering model chain works without any model settings and survives retired or failing models."""

import asyncio

import pytest
from langchain_core.runnables import RunnableLambda

from app.config import Settings, get_settings
from app.services import llm_factory

OSS_120B, OSS_20B, GEMINI = ("groq", "openai/gpt-oss-120b"), ("groq", "openai/gpt-oss-20b"), ("gemini", "gemini-2.5-flash")


@pytest.fixture
def settings(monkeypatch):
    """Both providers keyed, every model setting at its built-in default (nothing set in the environment)."""
    s = get_settings()
    for name in ("PRIMARY_LLM_PROVIDER", "PRIMARY_LLM_MODEL", "GROQ_MODEL", "GEMINI_MODEL", "FALLBACK_LLM_PROVIDER",
                 "FALLBACK_LLM_MODELS", "FALLBACK_LLM_MODEL", "QUERY_REWRITE_MODEL", "ENABLE_LLM_FALLBACK",
                 "GROQ_REASONING_EFFORT"):
        monkeypatch.setattr(s, name, Settings.model_fields[name].default)
    monkeypatch.setattr(s, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(s, "GOOGLE_API_KEY", "g_test")
    monkeypatch.setattr(s, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(s, "CLAUDE_MODEL", Settings.model_fields["CLAUDE_MODEL"].default)
    monkeypatch.setattr(llm_factory, "_groq_models", None)
    monkeypatch.setattr(llm_factory, "_warned", set())
    return s


def chain_of(llm) -> list[tuple[str, str]]:
    runnables = [llm.runnable, *llm.fallbacks] if hasattr(llm, "fallbacks") else [llm]
    return [(r.config["metadata"]["provider"], r.config["metadata"]["model"]) for r in runnables]


def test_no_model_settings_needed(settings):
    assert chain_of(llm_factory.get_configured_llm()) == [OSS_120B, OSS_20B, GEMINI]


def test_stale_retired_values_in_the_environment_still_work(settings, monkeypatch):
    # What an older render.yaml left in the Render dashboard
    monkeypatch.setattr(settings, "PRIMARY_LLM_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "FALLBACK_LLM_MODELS", "llama-3.1-8b-instant, openai/gpt-oss-120b, openai/gpt-oss-20b")
    monkeypatch.setattr(settings, "QUERY_REWRITE_MODEL", "llama-3.1-8b-instant")
    assert chain_of(llm_factory.get_configured_llm()) == [OSS_120B, OSS_20B, GEMINI]
    assert chain_of(llm_factory.get_rewrite_llm())[0] == OSS_20B


def test_models_groq_no_longer_serves_are_skipped(settings, monkeypatch):
    monkeypatch.setattr(llm_factory, "_groq_models", {"openai/gpt-oss-20b", "some/other-model"})
    assert chain_of(llm_factory.get_configured_llm()) == [OSS_20B, GEMINI]


def test_providers_without_a_key_are_skipped(settings, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    assert chain_of(llm_factory.get_configured_llm()) == [OSS_120B, OSS_20B]
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "g_test")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    assert chain_of(llm_factory.get_configured_llm()) == [GEMINI]


def test_extra_fallbacks_go_before_the_built_in_chain(settings, monkeypatch):
    monkeypatch.setattr(settings, "FALLBACK_LLM_MODELS", "gemini:gemini-2.5-pro")
    assert chain_of(llm_factory.get_configured_llm()) == [OSS_120B, ("gemini", "gemini-2.5-pro"), OSS_20B, GEMINI]


def test_no_keys_at_all_is_a_clear_error(settings, monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "")
    with pytest.raises(ValueError, match="GROQ_API_KEY or GOOGLE_API_KEY"):
        llm_factory.get_configured_llm()
    assert llm_factory.get_rewrite_llm() is None


def test_a_failing_model_falls_through_to_the_next(settings, monkeypatch):
    def fake_model(provider, model_name, **kwargs):
        def call(_messages):
            if model_name != "openai/gpt-oss-20b":
                raise RuntimeError(f"Error code: 404 - model {model_name} has been decommissioned")
            return "answer from gpt-oss-20b"
        return RunnableLambda(call)

    monkeypatch.setattr(llm_factory, "build_chat_model", fake_model)
    assert asyncio.run(llm_factory.get_configured_llm().ainvoke("hi")) == "answer from gpt-oss-20b"


def test_live_model_list_is_used(settings, monkeypatch):
    class Listing:
        data = [type("M", (), {"id": "openai/gpt-oss-120b", "active": True})(),
                type("M", (), {"id": "openai/gpt-oss-20b", "active": False})()]

    class FakeModels:
        async def list(self):
            return Listing()

    monkeypatch.setattr(llm_factory, "_groq_client", lambda key: type("Client", (), {"models": FakeModels()})())
    asyncio.run(llm_factory.refresh_groq_models())
    assert llm_factory._groq_models == {"openai/gpt-oss-120b"}
    assert chain_of(llm_factory.get_configured_llm()) == [OSS_120B, GEMINI]


def test_reasoning_effort_only_for_gpt_oss(settings):
    oss = llm_factory.build_chat_model("groq", "openai/gpt-oss-120b", "gsk_test")
    other = llm_factory.build_chat_model("groq", "qwen/qwen3.6-27b", "gsk_test")
    assert oss.reasoning_effort == "low"
    assert other.reasoning_effort is None


def test_fallbacks_are_tagged_for_the_model_switched_notice(settings):
    llm = llm_factory.get_configured_llm()
    assert llm.runnable.config["metadata"]["is_fallback"] is False
    assert all(f.config["metadata"]["is_fallback"] for f in llm.fallbacks)
    # The rewrite chain is internal: a switch there must not announce itself
    assert not any(r.config["metadata"]["is_fallback"] for r in [llm_factory.get_rewrite_llm().runnable])


def test_streaming_answer_falls_through_and_reports_the_switch(settings, monkeypatch):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    class Retired(GenericFakeChatModel):
        async def _astream(self, *args, **kwargs):
            raise RuntimeError("Error code: 404 - model_decommissioned")
            yield  # pragma: no cover

    def fake_model(provider, model_name, **kwargs):
        if model_name == "openai/gpt-oss-120b":
            return Retired(messages=iter([]))
        return GenericFakeChatModel(messages=iter([AIMessage(content="fallback answer")]))

    monkeypatch.setattr(llm_factory, "build_chat_model", fake_model)

    async def run():
        tokens, switched = [], []
        async for ev in llm_factory.get_configured_llm().astream_events("hi", version="v2"):
            if ev["event"] == "on_chat_model_start" and ev["metadata"].get("is_fallback"):
                switched.append(ev["metadata"]["model"])
            if ev["event"] == "on_chat_model_stream":
                tokens.append(ev["data"]["chunk"].content)
        return "".join(tokens), switched

    text, switched = asyncio.run(run())
    assert text == "fallback answer"
    assert switched == ["openai/gpt-oss-20b"]


def test_vision_chain_is_gemini_only_and_replaces_retired_names(settings, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
    assert chain_of(llm_factory.get_vision_llm()) == [GEMINI, ("gemini", "gemini-2.5-flash-lite")]


CLAUDE = ("anthropic", "claude-opus-5-5")


def test_claude_leads_when_its_key_is_set(settings, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    assert chain_of(llm_factory.get_configured_llm()) == [CLAUDE, OSS_120B, OSS_20B, GEMINI]
    # A request for a specific provider or model is honoured as asked
    assert chain_of(llm_factory.get_configured_llm(requested_provider="groq"))[0] == OSS_120B
    # The rewrite and vision chains stay on the small, fast models
    assert chain_of(llm_factory.get_rewrite_llm())[0] == OSS_20B


def test_claude_is_called_with_adaptive_thinking_and_effort_not_temperature(settings, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    llm = llm_factory.build_chat_model("anthropic", "claude-opus-5-5", "sk-ant-test", temperature=0.1)
    assert llm.thinking == {"type": "adaptive"}
    assert llm.output_config == {"effort": "medium"}
    assert llm.temperature is None and llm.max_retries == 1


def test_claude_handing_over_to_groq_is_silent(settings, monkeypatch):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    class Down(GenericFakeChatModel):
        async def _astream(self, *args, **kwargs):
            raise RuntimeError("Error code: 529 - overloaded_error")
            yield  # pragma: no cover

    def fake_model(provider, model_name, **kwargs):
        if provider == "anthropic":
            return Down(messages=iter([]))
        return GenericFakeChatModel(messages=iter([AIMessage(content="groq answer")]))

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm_factory, "build_chat_model", fake_model)

    async def run():
        tokens, notices, backups = [], [], []
        async for ev in llm_factory.get_configured_llm().astream_events("hi", version="v2"):
            if ev["event"] == "on_chat_model_start":
                if ev["metadata"].get("is_fallback") or "fallback_llm" in ev.get("tags", []):
                    notices.append(ev["metadata"]["model"])
                if ev["metadata"].get("backup"):
                    backups.append(ev["metadata"]["model"])
            if ev["event"] == "on_chat_model_stream":
                tokens.append(ev["data"]["chunk"].content)
        return "".join(tokens), notices, backups

    text, notices, backups = asyncio.run(run())
    assert text == "groq answer"
    assert notices == []                          # nothing tells the user
    assert backups == ["openai/gpt-oss-120b"]     # the metrics still record it
