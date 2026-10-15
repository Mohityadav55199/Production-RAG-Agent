"""
LLM Factory & Resilient Fallback Orchestrator.

Builds chat models for Claude (Anthropic), Groq and Google Gemini and chains them so a request still
gets an answer when a model is rate limited, down, or retired. The chain is built in; no environment
variable is needed:

  0. Claude (CLAUDE_MODEL), only when ANTHROPIC_API_KEY is set. If it fails the next model answers
     silently: no "model switched" notice is shown, the answer simply comes from Groq.
  1. the configured primary model (PRIMARY_LLM_MODEL / GROQ_MODEL / GEMINI_MODEL, or the built-in default),
  2. any extra FALLBACK_LLM_MODELS (optional),
  3. BUILT_IN_CHAIN, always appended.

Model names Groq or Google have retired are replaced with their successors (RETIRED_MODELS), and Groq
models missing from Groq's live model list (refreshed at startup and every few hours) are skipped, so a
stale value left in the deployment's environment cannot break chat. A provider without an API key is
skipped. Any error from one model moves on to the next.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Groq models that accept ``reasoning_effort`` (other models reject the parameter)
_REASONING_MODEL_PREFIXES = ("openai/gpt-oss",)

# Always tried, in this order, after the configured primary model and any FALLBACK_LLM_MODELS
BUILT_IN_CHAIN: tuple[tuple[str, str], ...] = (
    ("groq", "openai/gpt-oss-120b"),
    ("groq", "openai/gpt-oss-20b"),
    ("gemini", "gemini-2.5-flash"),
)

# The small, fast models used to rewrite follow-up questions (QUERY_REWRITE_MODEL goes first)
BUILT_IN_REWRITE_CHAIN: tuple[tuple[str, str], ...] = (
    ("groq", "openai/gpt-oss-20b"),
    ("groq", "openai/gpt-oss-120b"),
    ("gemini", "gemini-2.5-flash"),
)

# Image requests: Gemini only (GEMINI_MODEL goes first)
BUILT_IN_VISION_CHAIN: tuple[tuple[str, str], ...] = (
    ("gemini", "gemini-2.5-flash"),
    ("gemini", "gemini-2.5-flash-lite"),
)

# Shut-down models and their successors. A deployment whose environment still names one keeps working.
RETIRED_MODELS: dict[str, str] = {
    # Groq: free and developer tiers, 16 Aug 2026
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    # Groq: 17 Jul 2026
    "qwen/qwen3-32b": "openai/gpt-oss-120b",
    "meta-llama/llama-4-scout-17b-16e-instruct": "openai/gpt-oss-120b",
    # Groq: earlier retirements
    "llama3-70b-8192": "openai/gpt-oss-120b",
    "llama3-8b-8192": "openai/gpt-oss-20b",
    "mixtral-8x7b-32768": "openai/gpt-oss-120b",
    "gemma2-9b-it": "openai/gpt-oss-20b",
    # Google
    "gemini-1.5-flash": "gemini-2.5-flash",
    "gemini-1.5-pro": "gemini-2.5-flash",
}

_PROVIDER_ALIASES = {"google": "gemini", "google-genai": "gemini", "claude": "anthropic"}
_PROVIDERS = ("anthropic", "groq", "gemini")

# Room for Claude's thinking plus a long answer
_CLAUDE_MAX_TOKENS = 16000
# A slow or unreachable Claude gives way to Groq instead of keeping the user waiting
_CLAUDE_TIMEOUT_SECONDS = 60.0

# Groq's live model ids; None until fetched (then nothing is filtered out)
_groq_models: set[str] | None = None
_warned: set[str] = set()


def _is_reasoning_model(model_name: str) -> bool:
    return model_name.startswith(_REASONING_MODEL_PREFIXES)


def build_chat_model(
    provider: str,
    model_name: str,
    api_key: str | None = None,
    temperature: float = 0.1,
    streaming: bool = True,
    disable_streaming: bool = False,
) -> BaseChatModel:
    """
    Instantiate a chat model dynamically by provider name and model identifier.
    No model names or providers are hardcoded.
    """
    prov = (provider or "").lower().strip()

    if prov == "groq":
        from langchain_groq import ChatGroq

        extra: dict[str, Any] = {}
        if _is_reasoning_model(model_name):
            # gpt-oss thinks before answering; Groq returns that separately from the answer text.
            # Low effort keeps first-token latency close to a non-reasoning model.
            extra["reasoning_effort"] = get_settings().GROQ_REASONING_EFFORT or "low"
        return ChatGroq(
            model=model_name,
            groq_api_key=api_key or None,
            temperature=temperature,
            streaming=streaming,
            disable_streaming=disable_streaming,
            max_retries=2,
            **extra,
        )

    elif prov in ("anthropic", "claude"):
        from langchain_anthropic import ChatAnthropic

        # Thinking is adaptive on current Claude models (it cannot be switched off and they reject
        # temperature), so depth is set with effort instead. One retry, then the chain moves on.
        effort = (get_settings().CLAUDE_EFFORT or "medium").strip().lower()
        return ChatAnthropic(
            model=model_name,
            anthropic_api_key=api_key or None,
            max_tokens=_CLAUDE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            streaming=streaming,
            disable_streaming=disable_streaming,
            default_request_timeout=_CLAUDE_TIMEOUT_SECONDS,
            max_retries=1,
        )

    elif prov in ("gemini", "google", "google-genai"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key or None,
            temperature=temperature,
            streaming=streaming,
            convert_system_message_to_human=False,
            disable_streaming=disable_streaming,
            max_retries=2,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {provider!r}. Supported: 'anthropic', 'groq', 'gemini'.")


def _warn_once(key: str, message: str, *args) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def resolve_model(provider: str, model: str) -> str:
    """The model to call for *model*: its successor if it has been retired."""
    replacement = RETIRED_MODELS.get(model)
    if replacement:
        _warn_once(
            f"retired:{model}",
            "Model %s has been retired by %s; using %s instead. Remove it from the environment.",
            model, provider, replacement,
        )
        return replacement
    return model


def _groq_client(api_key: str):
    from groq import AsyncGroq

    return AsyncGroq(api_key=api_key, timeout=10.0)


async def refresh_groq_models() -> None:
    """Fetch the ids of the models Groq currently serves. Failures keep the previous list."""
    global _groq_models
    key = get_settings().GROQ_API_KEY
    if not key:
        return
    try:
        listing = await asyncio.wait_for(_groq_client(key).models.list(), timeout=15)
        ids = {m.id for m in listing.data if getattr(m, "active", True)}
        if ids:
            _groq_models = ids
            logger.info("Groq serves %d models", len(ids))
    except Exception as exc:  # noqa: BLE001 - the chain still falls back at request time
        logger.warning("Could not fetch Groq's model list: %s", exc)


async def keep_groq_models_fresh(interval_seconds: float = 6 * 3600) -> None:
    """Background task: refresh Groq's model list now and then every few hours."""
    while True:
        await refresh_groq_models()
        await asyncio.sleep(interval_seconds)


def _clean_key(value: str | None) -> str:
    """A key as pasted into a dashboard: surrounding spaces, newlines and quotes removed."""
    return (value or "").strip().strip("\"'").strip()


def _api_key(provider: str) -> str:
    s = get_settings()
    if provider == "anthropic":
        return _clean_key(s.ANTHROPIC_API_KEY)
    return s.GROQ_API_KEY if provider == "groq" else s.GOOGLE_API_KEY


def _usable(provider: str, model: str) -> bool:
    if not _api_key(provider):
        return False
    if provider == "groq" and _groq_models is not None and model not in _groq_models:
        _warn_once(f"missing:{model}", "Groq does not serve %s any more; skipping it", model)
        return False
    return True


def _parse_entry(entry: str, default_provider: str) -> tuple[str, str] | None:
    """'provider:model' or 'model' (with the default provider). Model ids may contain '/'."""
    entry = entry.strip()
    if not entry:
        return None
    prov, sep, mod = entry.partition(":")
    if sep and prov.strip().lower() in (*_PROVIDERS, *_PROVIDER_ALIASES):
        return _normalise_provider(prov), mod.strip()
    return default_provider, entry


def _normalise_provider(provider: str) -> str:
    p = (provider or "").strip().lower()
    return _PROVIDER_ALIASES.get(p, p)


def model_chain(
    primary: tuple[str, str] | None,
    extra: list[tuple[str, str]],
    built_in: tuple[tuple[str, str], ...],
) -> list[tuple[str, str]]:
    """Primary, then extras, then the built-in chain: retired names replaced, unusable and repeated ones dropped."""
    chain: list[tuple[str, str]] = []
    seen: set[str] = set()
    for provider, model in ([primary] if primary else []) + extra + list(built_in):
        provider = _normalise_provider(provider)
        model = resolve_model(provider, model)
        if provider not in _PROVIDERS or not model or model in seen:
            continue
        seen.add(model)
        if _usable(provider, model):
            chain.append((provider, model))
    return chain


def _primary_choice(requested_provider: str | None, requested_model: str | None) -> tuple[str, str] | None:
    s = get_settings()
    provider = _normalise_provider(requested_provider or s.PRIMARY_LLM_PROVIDER or "auto")
    if provider not in _PROVIDERS:  # "auto" or anything unknown
        provider = "groq" if s.GROQ_API_KEY else "gemini"
    configured = s.PRIMARY_LLM_MODEL if _normalise_provider(s.PRIMARY_LLM_PROVIDER) == provider else ""
    per_provider = {"anthropic": s.CLAUDE_MODEL, "groq": s.GROQ_MODEL}.get(provider, s.GEMINI_MODEL)
    model = requested_model or configured or per_provider
    return (provider, model) if model else None


def describe_llm_error(exc: BaseException) -> str:
    """The provider's own error message (e.g. "Your credit balance is too low"), without the request details."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return f"{err.get('type', type(exc).__name__)}: {err['message']}"
    return f"{type(exc).__name__}: {str(exc)[:300]}"


class _LogClaudeFailures(AsyncCallbackHandler):
    """Claude handing over to Groq is silent for users, so say why in the server log."""

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        logger.warning("Claude call failed, the next model answers instead: %s", describe_llm_error(error))


_claude_failure_logger = _LogClaudeFailures()


def _chain_llm(
    chain: list[tuple[str, str]],
    temperature: float,
    streaming: bool,
    tag_fallbacks: bool,
) -> BaseChatModel:
    if not chain:
        raise ValueError(
            "No language model is available: set ANTHROPIC_API_KEY, GROQ_API_KEY or GOOGLE_API_KEY on the server."
        )
    # Claude handing over to Groq is silent: nothing is tagged as a fallback, so no notice is shown
    # ("backup" still records the switch in the metrics).
    tag_fallbacks = tag_fallbacks and chain[0][0] != "anthropic"
    runnables = []
    for i, (provider, model) in enumerate(chain):
        is_fallback = tag_fallbacks and i > 0
        runnables.append(
            build_chat_model(
                provider=provider,
                model_name=model,
                api_key=_api_key(provider),
                temperature=temperature,
                streaming=streaming,
                disable_streaming=not streaming,
            ).with_config(
                tags=["fallback_llm" if is_fallback else "primary_llm", f"model:{model}"],
                metadata={"is_fallback": is_fallback, "backup": i > 0, "model": model, "provider": provider},
                callbacks=[_claude_failure_logger] if provider == "anthropic" else None,
            )
        )
    if len(runnables) == 1:
        return runnables[0]
    return runnables[0].with_fallbacks(runnables[1:])


def get_configured_llm(
    requested_provider: str | None = None,
    requested_model: str | None = None,
) -> BaseChatModel:
    """
    The answering model: the configured (or requested) primary, chained with fallbacks.

    Works with no model settings at all; see the module docstring for how the chain is built.
    """
    settings = get_settings()
    primary = _primary_choice(requested_provider, requested_model)
    extra: list[tuple[str, str]] = []
    built_in: tuple[tuple[str, str], ...] = ()
    if settings.ENABLE_LLM_FALLBACK:
        default_provider = _normalise_provider(settings.FALLBACK_LLM_PROVIDER) or "groq"
        raw = settings.FALLBACK_LLM_MODELS or settings.FALLBACK_LLM_MODEL or ""
        extra = [e for e in (_parse_entry(x, default_provider) for x in raw.split(",")) if e]
        built_in = BUILT_IN_CHAIN
    # Claude leads whenever it is keyed, unless a request asked for a specific provider or model
    # (model_chain drops it when ANTHROPIC_API_KEY is not set).
    if not (requested_provider or requested_model):
        extra = ([primary] if primary else []) + extra
        primary = ("anthropic", settings.CLAUDE_MODEL)
    chain = model_chain(primary, extra, built_in)
    if not settings.ENABLE_LLM_FALLBACK and not chain:
        chain = model_chain(None, [], BUILT_IN_CHAIN)[:1]   # the primary is unusable: still answer
    logger.debug("LLM chain: %s", " -> ".join(f"{p}:{m}" for p, m in chain))
    return _chain_llm(chain, settings.LLM_TEMPERATURE, streaming=True, tag_fallbacks=True)


def get_rewrite_llm() -> BaseChatModel | None:
    """Small non-streaming model chain for rewriting follow-up questions; None when no provider is keyed."""
    settings = get_settings()
    chain = model_chain(("groq", settings.QUERY_REWRITE_MODEL), [], BUILT_IN_REWRITE_CHAIN)
    if not chain:
        return None
    # Not tagged as fallbacks: a switch here is internal and must not show the "model switched" notice
    return _chain_llm(chain, 0.0, streaming=False, tag_fallbacks=False)


def get_vision_llm(streaming: bool = False) -> BaseChatModel:
    """Gemini chain for questions about images; GEMINI_MODEL first when set."""
    settings = get_settings()
    chain = model_chain(("gemini", settings.GEMINI_MODEL), [], BUILT_IN_VISION_CHAIN)
    if not chain:
        raise ValueError("Questions about images need a Gemini API key (GOOGLE_API_KEY).")
    return _chain_llm(chain, 0.1, streaming=streaming, tag_fallbacks=False)


async def check_claude(timeout_seconds: float = 90.0) -> dict:
    """Admin check: one tiny real request to Claude with the configured key, and what came back."""
    settings = get_settings()
    raw, key = settings.ANTHROPIC_API_KEY or "", _api_key("anthropic")
    result: dict[str, Any] = {"configured": bool(key), "model": settings.CLAUDE_MODEL, "ok": False, "error": None}
    if not key:
        result["error"] = "ANTHROPIC_API_KEY is not set on the server."
        return result
    if raw != key:
        result["note"] = "The key had spaces, a line break or quotes around it; they are ignored."
    if not key.startswith("sk-ant-"):
        result["error"] = "The key doesn't look like an Anthropic API key (they start with sk-ant-)."
        return result
    llm = build_chat_model("anthropic", settings.CLAUDE_MODEL, key, streaming=False, disable_streaming=True)
    try:
        reply = await asyncio.wait_for(llm.ainvoke([HumanMessage(content="Reply with the single word OK.")]),
                                       timeout=timeout_seconds)
        result["ok"] = True
        result["reply"] = (reply.text or "")[:40]
    except Exception as exc:  # noqa: BLE001 - reported to the admin as is
        result["error"] = describe_llm_error(exc)
    return result
