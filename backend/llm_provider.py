"""
ChipSutra LLM provider abstraction.

Supports THREE modes (auto-detected, in priority order):
1. Emergent Universal Key (Emergent-hosted): EMERGENT_LLM_KEY + emergentintegrations
2. Standalone SDKs (paid, best quality): ANTHROPIC_API_KEY and/or OPENAI_API_KEY
3. LOCAL OLLAMA (zero-cost, zero-key, DEFAULT for self-host): OLLAMA_URL
"""
import os
import logging
import json as _json
from typing import AsyncIterator, Optional
import httpx

logger = logging.getLogger("chipsutra.llm")

# --- Feature detection ---
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "chipsutra-vlsi:3b")

_emergent_ok = False
if EMERGENT_LLM_KEY:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone  # type: ignore
        _emergent_ok = True
    except Exception as e:
        logger.info(f"emergentintegrations not available ({e}); will try other providers")

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
        "ollama": bool(OLLAMA_URL),
        "ollama_model": OLLAMA_MODEL if OLLAMA_URL else None,
    }


async def stream_chat(provider: str, model: str, system: str, user_text: str, session_id: Optional[str] = None) -> AsyncIterator[str]:
    """Yield text deltas from the chosen LLM provider.
    Provider precedence: emergent → anthropic (if provider=='anthropic') → openai (if provider=='openai') → ollama (fallback).
    """
    # Prefer Emergent if configured (covers all providers under one key)
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

    # Standalone SDKs
    if provider == "anthropic" and _anthropic_client:
        async with _anthropic_client.messages.stream(
            model=model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
        return

    if provider == "openai" and _openai_client:
        stream = await _openai_client.chat.completions.create(
            model=model, stream=True,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        )
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            except (IndexError, AttributeError):
                continue
        return

    # OLLAMA FALLBACK — zero-key, zero-cost, runs locally
    if OLLAMA_URL:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj = _json.loads(line)
                    except Exception:
                        continue
                    if obj.get("done"):
                        break
                    msg = obj.get("message", {})
                    content = msg.get("content", "")
                    if content:
                        yield content
        return

    raise RuntimeError(
        f"No LLM provider configured for '{provider}'. Set OLLAMA_URL for zero-key local mode, "
        "or ANTHROPIC_API_KEY / OPENAI_API_KEY / EMERGENT_LLM_KEY."
    )

