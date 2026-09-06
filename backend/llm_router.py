"""Model router + Ollama pre-warm for ChipSutra-VLSI.

Picks 3B vs 7B (when installed) from DV planner tier. Prefer 7B for quality TB.
Pre-warms preferred model on API startup to cut first-token latency.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from llm_provider import ollama_runtime_options

logger = logging.getLogger("chipsutra.llm_router")

_PREWARM_STATE: Dict[str, Any] = {
    "attempted": False,
    "ok": False,
    "model": None,
    "error": None,
}


def model_3b() -> str:
    return os.environ.get("CHIPSUTRA_MODEL_3B") or "chipsutra-vlsi:3b"


def model_7b() -> str:
    return os.environ.get("CHIPSUTRA_MODEL_7B") or "chipsutra-vlsi:7b"


def model_14b() -> str:
    return os.environ.get("CHIPSUTRA_MODEL_14B") or "chipsutra-vlsi:14b"


def preferred_model() -> str:
    """Product default: 7B when set via OLLAMA_MODEL, else chipsutra-vlsi:7b."""
    env = (os.environ.get("OLLAMA_MODEL") or "").strip()
    if env:
        return env
    return model_7b()


def _installed_names(ollama_url: str) -> List[str]:
    try:
        import requests as _req

        r = _req.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=4)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception as e:
        logger.debug("ollama tags failed: %s", e)
        return []


def _pick_installed(installed: List[str], want: str) -> Optional[str]:
    if not want or not installed:
        return None
    if want in installed:
        return want
    base = want.split(":")[0]
    for n in installed:
        if n == want or n.split(":")[0] == base:
            # Prefer exact tag match when multiple tags share base
            if n == want:
                return n
    for n in installed:
        if n.split(":")[0] == base:
            return n
    return None


def _name_matches(installed: List[str], want: str) -> bool:
    return _pick_installed(installed, want) is not None


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
    req = (requested_model or "").strip() or preferred_model()
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
    want14 = model_14b()
    want7 = model_7b()
    want3 = model_3b()
    prefer_7 = "7b" in tier or os.environ.get("CHIPSUTRA_PREFER_7B", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    prefer_14 = "14b" in tier or os.environ.get("CHIPSUTRA_PREFER_14B", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Explicit user force: keep requested if installed and CHIPSUTRA_FORCE_REQUESTED=1
    force_req = os.environ.get("CHIPSUTRA_FORCE_REQUESTED", "").lower() in ("1", "true", "yes")
    if force_req and _name_matches(installed, req):
        return {
            "provider": "ollama",
            "model": _pick_installed(installed, req) or req,
            "tier_requested": tier,
            "reason": "forced_requested",
            "installed_sample": installed[:6],
        }

    # Honor an explicit 3B tier (simple combo). PREFER_7B must not override it.
    if tier in ("3b", "3b_preferred", "small") and _name_matches(installed, want3):
        return {
            "provider": "ollama",
            "model": _pick_installed(installed, want3) or want3,
            "tier_requested": tier,
            "reason": "tier_3b",
            "installed_sample": installed[:6],
        }

    # 14B for complex SoC/UVM when installed and tier asks for it
    if prefer_14 and _name_matches(installed, want14):
        return {
            "provider": "ollama",
            "model": _pick_installed(installed, want14) or want14,
            "tier_requested": tier,
            "reason": "tier_14b_available",
            "installed_sample": installed[:6],
        }

    if prefer_7 and _name_matches(installed, want7):
        picked = _pick_installed(installed, want7)
        return {
            "provider": "ollama",
            "model": picked or want7,
            "tier_requested": tier,
            "reason": "tier_7b_available" if "7b" in tier else "prefer_7b_available",
            "installed_sample": installed[:6],
        }

    # Prefer exact requested if installed
    if _name_matches(installed, req):
        return {
            "provider": "ollama",
            "model": _pick_installed(installed, req) or req,
            "tier_requested": tier,
            "reason": "requested_installed",
            "installed_sample": installed[:6],
        }

    if _name_matches(installed, want3):
        return {
            "provider": "ollama",
            "model": _pick_installed(installed, want3) or want3,
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
    tag = model or preferred_model()
    # If preferred is 7b but not installed yet, fall back to 3b for prewarm
    if url:
        installed = _installed_names(url)
        if not _name_matches(installed, tag) and _name_matches(installed, model_3b()):
            tag = _pick_installed(installed, model_3b()) or model_3b()
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
        "keep_alive": os.environ.get("OLLAMA_KEEP_ALIVE", "30m"),
        "options": ollama_runtime_options(num_predict=4, extra={"temperature": 0}),
    }
    try:
        timeout = float(os.environ.get("OLLAMA_PREWARM_TIMEOUT", "180"))
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
