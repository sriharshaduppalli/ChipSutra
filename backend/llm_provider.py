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
# Product default: ChipSutra-VLSI only. Set SHOW_CLOUD_MODELS=true to expose Claude/GPT in the UI.
SHOW_CLOUD_MODELS = os.environ.get("SHOW_CLOUD_MODELS", "false").lower() in ("1", "true", "yes")


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
    cloud = SHOW_CLOUD_MODELS
    return {
        "emergent": _emergent_ok,
        "anthropic": cloud and (_anthropic_client is not None or _emergent_ok),
        "openai": cloud and (_openai_client is not None or _emergent_ok),
        "ollama": bool(OLLAMA_URL),
        "ollama_model": OLLAMA_MODEL if OLLAMA_URL else None,
        "show_cloud_models": cloud,
        "product_model": {
            "provider": "ollama",
            "model": OLLAMA_MODEL,
            "label": "ChipSutra-VLSI",
        },
    }


def ollama_status() -> dict:
    """Sync probe for /api/health — is the configured model present?"""
    out = {"configured": bool(OLLAMA_URL), "model": OLLAMA_MODEL, "ready": False}
    if not OLLAMA_URL:
        return out
    try:
        import requests as _req
        r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=4)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        want = OLLAMA_MODEL
        out["ready"] = any(n == want or n.split(":")[0] == want.split(":")[0] for n in names)
        if not out["ready"] and names:
            out["installed"] = names[:8]
    except Exception as e:
        out["error"] = str(e)[:240]
    return out


async def stream_chat(
    provider: str,
    model: str,
    system: str,
    user_text: str,
    session_id: Optional[str] = None,
    *,
    num_predict: Optional[int] = None,
) -> AsyncIterator[str]:
    """Yield text deltas from the chosen LLM provider.

    Respect the UI selection:
      - provider=ollama → local ChipSutra-VLSI (never hijack to Emergent/Claude)
      - provider=anthropic|openai → cloud SDKs, or Emergent universal key if set
      - provider=emergent → Emergent only
    """
    prov = (provider or "ollama").lower().strip()

    async def _via_emergent(p: str, m: str) -> AsyncIterator[str]:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id or "chipsutra",
            system_message=system,
        ).with_model(p, m)
        async for ev in chat.stream_message(UserMessage(text=user_text)):
            if isinstance(ev, TextDelta):
                yield ev.content
            elif isinstance(ev, StreamDone):
                break

    # ChipSutra-VLSI first when asked (or default) and Ollama is configured.
    if prov in ("ollama", "chipsutra", "chipsutra-vlsi", "") and OLLAMA_URL:
        if num_predict is None:
            num_predict = int(os.environ.get("OLLAMA_NUM_PREDICT", "700"))
        use_model = model if (model or "").strip() else OLLAMA_MODEL
        payload = {
            "model": use_model or OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "stream": True,
            "options": {
                "temperature": float(os.environ.get("OLLAMA_TEMPERATURE", "0.08")),
                "num_predict": int(num_predict),
                "repeat_penalty": float(os.environ.get("OLLAMA_REPEAT_PENALTY", "1.18")),
                "top_p": float(os.environ.get("OLLAMA_TOP_P", "0.85")),
            },
        }
        ollama_timeout = float(os.environ.get("OLLAMA_HTTP_TIMEOUT", "300"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(ollama_timeout, connect=20.0)) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", errors="ignore")[:500]
                    hint = (
                        f"Ollama returned {resp.status_code} for model '{payload['model']}'. "
                        "Run: docker compose up (builds chipsutra-vlsi automatically) or "
                        "'ollama create chipsutra-vlsi:3b -f modelfiles/Modelfile.3b' from ChipSutra-VLSI-LLM."
                    )
                    raise RuntimeError(f"{hint} Detail: {body or resp.reason_phrase}")
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

    # Cloud via Emergent universal key (only when user selected anthropic/openai/emergent)
    if _emergent_ok and prov in ("anthropic", "openai", "emergent"):
        cloud_provider = "openai" if prov == "emergent" and "gpt" in (model or "").lower() else (
            "anthropic" if prov == "emergent" else prov
        )
        async for delta in _via_emergent(cloud_provider if prov == "emergent" else prov, model):
            yield delta
        return

    # Standalone SDKs
    if prov == "anthropic" and _anthropic_client:
        async with _anthropic_client.messages.stream(
            model=model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            async for chunk in stream.text_stream:
                yield chunk
        return

    if prov == "openai" and _openai_client:
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

    # Last resort: Emergent only if Ollama missing and key present (legacy hosted demo)
    if _emergent_ok and not OLLAMA_URL:
        async for delta in _via_emergent(
            "anthropic" if "claude" in (model or "").lower() else "openai",
            model or "claude-sonnet-4-5-20250929",
        ):
            yield delta
        return

    raise RuntimeError(
        f"No LLM provider configured for '{provider}'. Set OLLAMA_URL for ChipSutra-VLSI, "
        "or ANTHROPIC_API_KEY / OPENAI_API_KEY / EMERGENT_LLM_KEY (with SHOW_CLOUD_MODELS=true)."
    )

