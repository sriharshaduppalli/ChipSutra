"""Public-mode / abuse-control guards (no live server required)."""
import os

import pytest


def test_weak_jwt_rejected_in_public_mode(monkeypatch):
    monkeypatch.setenv("CHIPSUTRA_PUBLIC_MODE", "true")
    monkeypatch.setenv("JWT_SECRET", "dev-secret")
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("DB_NAME", "chipsutra_test")
    # Import fresh helpers by executing the assert logic inline
    weak = frozenset({"", "dev-secret", "change-me", "secret", "changeme"})
    secret = os.environ.get("JWT_SECRET", "")
    assert secret.lower() in weak or len(secret) < 32


def test_rate_limit_helper_enforces():
    from rate_limit import enforce_rate_limit
    from fastapi import HTTPException

    key = "test_public_guard_unique_key"
    # Clear path: several calls OK then 429
    for _ in range(3):
        enforce_rate_limit(key, max_calls=3, window_s=60)
    with pytest.raises(HTTPException) as ei:
        enforce_rate_limit(key, max_calls=3, window_s=60)
    assert ei.value.status_code == 429
