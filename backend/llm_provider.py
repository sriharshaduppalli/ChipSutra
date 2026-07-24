"""
ChipSutra LLM provider abstraction.

Supports two modes:
1. Emergent Universal Key (default in Emergent-hosted environment):
   set EMERGENT_LLM_KEY, and the `emergentintegrations` library.
2. Standalone / open-source:
   set ANTHROPIC_API_KEY (for Claude) and/or OPENAI_API_KEY (for GPT).

Public API:
    async for delta in stream_chat(provider, model, system, user_text):
        # delta is a text chunk string
"""
import os
import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger("chipsutra.llm")

# --- Feature detection ---
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

_emergent_ok = False
if EMERGENT_LLM_KEY:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone  # type: ignore
        _emergent_ok = True
    except Exception as e:
        logger.info(f"emergentintegrations not available ({e}); will use standalone SDKs")

_anthropic_client = None
if ANTHROPIC_API_KEY:
    try:
        import anthropic  # type: ignore
        _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as e:
        logger.warning(f"anthropic SDK init failed: {e}")

_openai_client = None
if OPENAI_API_KEY:
    try:
        import openai  # type: ignore
        _openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        logger.warning(f"openai SDK init failed: {e}")


def available_providers() -> dict:
    return {
        "emergent": _emergent_ok,
        "anthropic": _anthropic_client is not None,
        "openai": _openai_client is not None,
    }


async def stream_chat(provider: str, model: str, system: str, user_text: str, session_id: Optional[str] = None) -> AsyncIterator[str]:
    """Yield text deltas from the chosen LLM provider."""
    # Prefer Emergent if available and configured (single key for all providers)
    if _emergent_ok:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id or "chipsutra",
            system_message=system,
        ).with_model(provider, model)
        async for ev in chat.stream_message(UserMessage(text=user_text)):
            if isinstance(ev, TextDelta):
                yield ev.content
            elif isinstance(ev, StreamDone):
                break
        return

    # Standalone paths
    if provider == "anthropic":
        if not _anthropic_client:
            raise RuntimeError("Anthropic provider not configured. Set ANTHROPIC_API_KEY.")
        async with _anthropic_client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
        return

    if provider == "openai":
        if not _openai_client:
            raise RuntimeError("OpenAI provider not configured. Set OPENAI_API_KEY.")
        stream = await _openai_client.chat.completions.create(
            model=model,
            stream=True,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
        )
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            except (IndexError, AttributeError):
                continue
        return

    raise RuntimeError(f"Unknown provider: {provider}")
