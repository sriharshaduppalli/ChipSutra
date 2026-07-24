"""
ChipSutra object storage abstraction.

Modes:
- 'emergent' (default in Emergent-hosted env): uses integrations.emergentagent.com
- 'local'   (default for self-host): writes to STORAGE_LOCAL_PATH on disk

Public API:
    put_object(path, data_bytes, content_type) -> {"path": <returned path>}
    get_object(path) -> (data_bytes, content_type)
    storage_mode() -> "emergent" | "local"
"""
import os
import logging
from pathlib import Path
import requests

logger = logging.getLogger("chipsutra.storage")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
STORAGE_MODE = os.environ.get("STORAGE_MODE", "auto").lower()
LOCAL_ROOT = Path(os.environ.get("STORAGE_LOCAL_PATH", "./storage")).resolve()

EMERGENT_STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
_emergent_storage_key = None
_active_mode = None


def _init_emergent():
    global _emergent_storage_key
    if _emergent_storage_key:
        return True
    if not EMERGENT_LLM_KEY:
        return False
    try:
        r = requests.post(f"{EMERGENT_STORAGE_URL}/init", json={"emergent_key": EMERGENT_LLM_KEY}, timeout=15)
        r.raise_for_status()
        _emergent_storage_key = r.json()["storage_key"]
        logger.info("Emergent object storage initialised")
        return True
    except Exception as e:
        logger.info(f"Emergent storage unavailable ({e}); falling back to local")
        return False


def _init_local():
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info(f"Local storage initialised at {LOCAL_ROOT}")


def init_storage() -> str:
    """Return the active storage mode: 'emergent' or 'local'."""
    global _active_mode
    if _active_mode:
        return _active_mode
    if STORAGE_MODE == "emergent" or (STORAGE_MODE == "auto" and EMERGENT_LLM_KEY):
        if _init_emergent():
            _active_mode = "emergent"
            return _active_mode
    # Fallback to local
    _init_local()
    _active_mode = "local"
    return _active_mode


def storage_mode() -> str:
    return _active_mode or init_storage()


def put_object(path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    mode = storage_mode()
    if mode == "emergent":
        r = requests.put(
            f"{EMERGENT_STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": _emergent_storage_key, "Content-Type": content_type},
            data=data, timeout=120,
        )
        r.raise_for_status()
        return r.json()
    # Local
    full = LOCAL_ROOT / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return {"path": path}


def get_object(path: str) -> tuple[bytes, str]:
    mode = storage_mode()
    if mode == "emergent":
        r = requests.get(
            f"{EMERGENT_STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": _emergent_storage_key}, timeout=60,
        )
        r.raise_for_status()
        return r.content, r.headers.get("Content-Type", "application/octet-stream")
    # Local
    full = LOCAL_ROOT / path
    if not full.exists():
        raise FileNotFoundError(path)
    return full.read_bytes(), "application/octet-stream"
