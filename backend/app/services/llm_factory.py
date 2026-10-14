"""
LLM Factory & Resilient Fallback Orchestrator.

Provides dynamic, non-hardcoded chat model creation supporting multiple providers
(Groq, Google Gemini) with automatic graceful fallback when the primary provider
hits rate limits (429), timeouts, or service disruptions.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def build_chat_model(
    provider: str,
    model_name: str,
    api_key: str | None = None,
    temperature: float = 0.1,
    streaming: bool = True,
) -> BaseChatModel:
    """
    Instantiate a chat model dynamically by provider name and model identifier.
    No model names or providers are hardcoded.
    """
    prov = (provider or "").lower().strip()

    if prov == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model_name,
            groq_api_key=api_key or None,
            temperature=temperature,
            streaming=streaming,
            max_retries=2,
        )

    elif prov in ("gemini", "google", "google-genai"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key or None,
            temperature=temperature,
            streaming=streaming,
            convert_system_message_to_human=False,
            max_retries=2,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: {provider!r}. Supported: 'groq', 'gemini'.")


def get_configured_llm(
    requested_provider: str | None = None,
    requested_model: str | None = None,
) -> BaseChatModel:
    """
    Build the active LLM with automatic fallback support.

    Configuration resolution:
      1. If provider/model is explicitly requested, use that as primary.
      2. Otherwise, check PRIMARY_LLM_PROVIDER and PRIMARY_LLM_MODEL from config.
      3. If primary provider key is not available, auto-detect available keys.
      4. If ENABLE_LLM_FALLBACK is true and a fallback model can be configured,
         chain it using `.with_fallbacks([fallback_llm])`.
    """
    settings = get_settings()

    # Determine primary provider & model
    primary_provider = (
        requested_provider
        or getattr(settings, "PRIMARY_LLM_PROVIDER", None)
        or ("groq" if settings.GROQ_API_KEY else "gemini")
    ).lower()

    if primary_provider == "groq":
        primary_model = requested_model or settings.GROQ_MODEL or "llama-3.3-70b-versatile"
        primary_key = settings.GROQ_API_KEY
    else:
        primary_model = requested_model or settings.GEMINI_MODEL or "gemini-2.5-flash"
        primary_key = settings.GOOGLE_API_KEY

    # Auto-switch if primary key is missing but alternative is present
    if primary_provider == "groq" and not primary_key and settings.GOOGLE_API_KEY:
        logger.warning("GROQ_API_KEY is not configured; falling back to Gemini as primary")
        primary_provider = "gemini"
        primary_model = settings.GEMINI_MODEL or "gemini-2.5-flash"
        primary_key = settings.GOOGLE_API_KEY
    elif primary_provider == "gemini" and not primary_key and settings.GROQ_API_KEY:
        logger.warning("GOOGLE_API_KEY is not configured; falling back to Groq as primary")
        primary_provider = "groq"
        primary_model = settings.GROQ_MODEL or "llama-3.3-70b-versatile"
        primary_key = settings.GROQ_API_KEY

    logger.info("Initializing primary LLM: provider=%s, model=%s", primary_provider, primary_model)

    primary_llm = build_chat_model(
        provider=primary_provider,
        model_name=primary_model,
        api_key=primary_key,
        temperature=getattr(settings, "LLM_TEMPERATURE", 0.1),
        streaming=True,
    )

    # ── Fallback Model Chain Resolution ───────────────────────────────────────
    enable_fallback = getattr(settings, "ENABLE_LLM_FALLBACK", True)
    if not enable_fallback:
        return primary_llm

    fallbacks: list[BaseChatModel] = []
    
    # Parse multi-model fallback chain from settings (comma-separated list)
    raw_fallback_models = (
        getattr(settings, "FALLBACK_LLM_MODELS", "")
        or getattr(settings, "FALLBACK_LLM_MODEL", "")
    )
    model_entries = [m.strip() for m in raw_fallback_models.split(",") if m.strip()]
    default_fallback_provider = getattr(settings, "FALLBACK_LLM_PROVIDER", "").lower().strip() or "groq"
    
    seen_models = {primary_model}

    for entry in model_entries:
        # Supports format "provider:model" (e.g. "gemini:gemini-2.5-flash") or simple "model" (e.g. "mixtral-8x7b-32768")
        if ":" in entry:
            prov, mod = entry.split(":", 1)
            prov = prov.strip().lower()
            mod = mod.strip()
        else:
            prov = default_fallback_provider
            mod = entry

        if not mod or mod in seen_models:
            continue
        seen_models.add(mod)

        # Validate that the API key for this provider exists
        if prov == "groq" and settings.GROQ_API_KEY:
            key = settings.GROQ_API_KEY
        elif prov in ("gemini", "google") and settings.GOOGLE_API_KEY:
            key = settings.GOOGLE_API_KEY
        else:
            continue

        try:
            logger.info("Adding fallback model to resilience chain: provider=%s, model=%s", prov, mod)
            fb_llm = build_chat_model(
                provider=prov,
                model_name=mod,
                api_key=key,
                temperature=getattr(settings, "FALLBACK_LLM_TEMPERATURE", 0.1),
                streaming=True,
            )
            fallbacks.append(fb_llm)
        except Exception as exc:
            logger.warning("Could not initialize fallback model %s:%s — %s", prov, mod, exc)

    # Emergency fallback if list was empty or couldn't resolve
    if not fallbacks and settings.GROQ_API_KEY:
        for backup in ["llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]:
            if backup not in seen_models:
                fallbacks.append(
                    build_chat_model(
                        provider="groq",
                        model_name=backup,
                        api_key=settings.GROQ_API_KEY,
                        temperature=0.1,
                        streaming=True,
                    )
                )
                seen_models.add(backup)
                break

    if fallbacks:
        logger.info("Chaining primary LLM '%s' with %d fallback model(s)", primary_model, len(fallbacks))
        return primary_llm.with_fallbacks(fallbacks)

    return primary_llm
