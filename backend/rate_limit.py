"""
Rate limiting with a Redis backend and a transparent in-memory fallback.

Drop-in replacement for server.py's in-memory `_rate_limit(key, max_calls, window_s)`:
`enforce_rate_limit(...)` raises HTTPException 429 with the same semantics.

Redis is optional — it is used only when the `redis` package is importable and
`REDIS_URL` is set; any connection/command error degrades to the memory bucket so a
single-process deployment keeps working. Multi-worker deployments should set
`REDIS_URL` so the window is shared.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

try:  # fastapi is a hard dependency of the server, but keep this module importable standalone
    from fastapi import HTTPException
except Exception:  # pragma: no cover - only hit in a stripped environment

    class HTTPException(Exception):  # type: ignore[no-redef]
        def __init__(self, status_code: int, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail


REDIS_KEY_PREFIX = "chipsutra:ratelimit:"

# Self-contained memory path: key -> sliding window of call timestamps.
_mem_buckets: Dict[str, List[float]] = {}
_mem_lock = threading.Lock()

_redis = None
_redis_tried = False
_redis_healthy = False
_note = ""


def _redis_url() -> str:
    return (os.environ.get("REDIS_URL") or "").strip()


def redis_client():
    """Lazily create and cache a redis client, or None. Never raises."""
    global _redis, _redis_tried, _redis_healthy, _note
    if _redis_tried:
        return _redis
    _redis_tried = True
    url = _redis_url()
    if not url:
        _note = "REDIS_URL not set; using in-memory limiter"
        return None
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=float(os.environ.get("REDIS_TIMEOUT_S", "1.0")),
            socket_timeout=float(os.environ.get("REDIS_TIMEOUT_S", "1.0")),
        )
        client.ping()
        _redis = client
        _redis_healthy = True
        _note = "redis limiter active (shared across workers)"
    except ImportError:
        _note = "redis package not installed; using in-memory limiter"
    except Exception as e:
        _note = f"redis unreachable ({e}); using in-memory limiter"
    return _redis


def limiter_backend() -> str:
    """"redis" | "memory"."""
    return "redis" if redis_client() is not None else "memory"


def reset_limiter_cache() -> None:
    """Forget the cached client so the next call re-resolves REDIS_URL (tests/config reload)."""
    global _redis, _redis_tried, _redis_healthy, _note
    _redis = None
    _redis_tried = False
    _redis_healthy = False
    _note = ""


def reset_rate_limit(key: Optional[str] = None) -> None:
    """Clear one key (or every key) from the memory bucket and Redis when present."""
    with _mem_lock:
        if key is None:
            _mem_buckets.clear()
        else:
            _mem_buckets.pop(key, None)
    client = redis_client()
    if client is None:
        return
    try:
        if key is None:
            for k in client.scan_iter(match=f"{REDIS_KEY_PREFIX}*"):
                client.delete(k)
        else:
            client.delete(REDIS_KEY_PREFIX + key)
    except Exception:
        pass


def _check_memory(key: str, max_calls: int, window_s: float) -> dict:
    """Sliding window, same semantics as server.py's original `_rate_limit`."""
    now = time.time()
    with _mem_lock:
        buf = _mem_buckets.setdefault(key, [])
        while buf and buf[0] < now - window_s:
            buf.pop(0)
        if len(buf) >= max_calls:
            return {
                "allowed": False,
                "remaining": 0,
                "reset_in": round(max(0.0, (buf[0] + window_s) - now), 3),
                "backend": "memory",
            }
        buf.append(now)
        return {
            "allowed": True,
            "remaining": max(0, max_calls - len(buf)),
            "reset_in": round(max(0.0, (buf[0] + window_s) - now), 3),
            "backend": "memory",
        }


def _check_redis(client, key: str, max_calls: int, window_s: float) -> dict:
    """Fixed window: INCR then EXPIRE on first hit of the window."""
    rkey = REDIS_KEY_PREFIX + key
    pipe = client.pipeline()
    pipe.incr(rkey, 1)
    pipe.ttl(rkey)
    count, ttl = pipe.execute()
    count = int(count)
    ttl = int(ttl)
    if count == 1 or ttl < 0:
        client.expire(rkey, max(1, int(round(window_s))))
        ttl = max(1, int(round(window_s)))
    return {
        "allowed": count <= max_calls,
        "remaining": max(0, max_calls - count),
        "reset_in": float(max(0, ttl)),
        "backend": "redis",
    }


def check_rate_limit(key: str, max_calls: int = 10, window_s: float = 60.0) -> dict:
    """Consume one token for `key`.

    Returns {"allowed", "remaining", "reset_in", "backend"}. Never raises: a Redis
    error at call time transparently falls back to the memory bucket.
    """
    global _redis, _redis_healthy, _note
    client = redis_client()
    if client is not None:
        try:
            return _check_redis(client, key, max_calls, window_s)
        except Exception as e:
            _note = f"redis call failed ({e}); fell back to in-memory limiter"
            _redis = None
            _redis_healthy = False
            result = _check_memory(key, max_calls, window_s)
            result["note"] = _note
            return result
    return _check_memory(key, max_calls, window_s)


def enforce_rate_limit(key: str, max_calls: int = 10, window_s: float = 60.0) -> dict:
    """Drop-in for server.py's `_rate_limit`: raises HTTPException 429 when over budget."""
    result = check_rate_limit(key, max_calls=max_calls, window_s=window_s)
    if not result["allowed"]:
        raise HTTPException(429, "Too many requests. Try again in a moment.")
    return result


def rate_limit_status() -> dict:
    backend = limiter_backend()
    healthy = True
    if backend == "redis":
        try:
            healthy = bool(redis_client().ping())
        except Exception:
            healthy = False
    return {
        "backend": backend,
        "redis_url_set": bool(_redis_url()),
        "healthy": healthy,
        "note": _note,
        "tracked_keys": len(_mem_buckets),
    }
