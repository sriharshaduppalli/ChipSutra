"""Model router + Ollama pre-warm for ChipSutra-VLSI.

Picks 3B vs 7B (when installed) from DV planner tier. Pre-warms default model
on API startup to cut first-token latency.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chipsutra.llm_router")

_PREWARM_STATE: Dict[str, Any] = {
    "attempted": False,
    "ok": False,
    "model": None,
    "error": None,
}


def model_3b() -> str:
    return os.environ.get("CHIPSUTRA_MODEL_3B") or os.environ.get("OLLAMA_MODEL") or "chipsutra-vlsi:3b"


def model_7b() -> str:
    return os.environ.get("CHIPSUTRA_MODEL_7B") or "chipsutra-vlsi:7b"


def _installed_names(ollama_url: str) -> List[str]:
    try:
        import requests as _req

        r = _req.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=4)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as e:
        logger.debug("ollama tags failed: %s", e)
        return []


def _name_matches(installed: List[str], want: str) -> bool:
    if not want:
        return False
    return any(n == want or n.split(":")[0] == want.split(":")[0] for n in installed)


def resolve_model(
    *,
    provider: str,
    requested_model: str,
    model_tier: str = "3b",
    ollama_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve which model tag to call.

    For non-ollama providers, returns requested_model unchanged.
    For ollama: prefer 7b when tier says so and tag is installed; else 3b / requested.
    """
    prov = (provider or "ollama").lower()
    req = (requested_model or "").strip() or model_3b()
    tier = (model_tier or "3b").lower()

    if prov not in ("ollama", "local"):
        return {
            "provider": prov,
            "model": req,
            "tier_requested": tier,
            "reason": "non_ollama_passthrough",
        }

    url = (ollama_url or os.environ.get("OLLAMA_URL") or "").rstrip("/")
    if not url:
        return {
            "provider": "ollama",
            "model": req,
            "tier_requested": tier,
            "reason": "ollama_url_unset",
        }

    installed = _installed_names(url)
    want7 = model_7b()
    want3 = model_3b()

    if "7b" in tier and _name_matches(installed, want7):
        return {
            "provider": "ollama",
            "model": want7 if want7 in installed or _name_matches(installed, want7) else next(
                (n for n in installed if "7b" in n), want7
            ),
            "tier_requested": tier,
            "reason": "tier_7b_available",
            "installed_sample": installed[:6],
        }

    # Prefer exact requested if installed
    if _name_matches(installed, req):
        return {
            "provider": "ollama",
            "model": req,
            "tier_requested": tier,
            "reason": "requested_installed",
            "installed_sample": installed[:6],
        }

    if _name_matches(installed, want3):
        return {
            "provider": "ollama",
            "model": want3,
            "tier_requested": tier,
            "reason": "fallback_3b",
            "installed_sample": installed[:6],
        }

    return {
        "provider": "ollama",
        "model": req or want3,
        "tier_requested": tier,
        "reason": "best_effort_unverified",
        "installed_sample": installed[:6],
    }


async def prewarm_ollama(model: Optional[str] = None) -> Dict[str, Any]:
    """Fire a tiny chat so Ollama loads weights before the first user Generate."""
    global _PREWARM_STATE
    url = (os.environ.get("OLLAMA_URL") or "").rstrip("/")
    tag = model or model_3b()
    _PREWARM_STATE = {"attempted": True, "ok": False, "model": tag, "error": None}
    if not url:
        _PREWARM_STATE["error"] = "OLLAMA_URL unset"
        return _PREWARM_STATE
    if os.environ.get("OLLAMA_PREWARM", "true").lower() in ("0", "false", "no"):
        _PREWARM_STATE["error"] = "disabled"
        return _PREWARM_STATE

    import httpx

    payload = {
        "model": tag,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "stream": False,
        "options": {"num_predict": 4, "temperature": 0},
    }
    try:
        timeout = float(os.environ.get("OLLAMA_PREWARM_TIMEOUT", "120"))
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            r = await client.post(f"{url}/api/chat", json=payload)
            if r.status_code >= 400:
                _PREWARM_STATE["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
                logger.warning("Ollama prewarm failed: %s", _PREWARM_STATE["error"])
            else:
                _PREWARM_STATE["ok"] = True
                logger.info("Ollama prewarm OK model=%s", tag)
    except Exception as e:
        _PREWARM_STATE["error"] = str(e)[:240]
        logger.warning("Ollama prewarm error: %s", _PREWARM_STATE["error"])
    return dict(_PREWARM_STATE)


def prewarm_status() -> Dict[str, Any]:
    return dict(_PREWARM_STATE)
