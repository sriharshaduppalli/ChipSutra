"""Router 14B tier selection (mocked installed tags)."""
from unittest.mock import patch

import llm_router


def test_resolve_prefers_14b_when_tier_asks():
    with patch.object(llm_router, "_installed_names", return_value=["chipsutra-vlsi:14b", "chipsutra-vlsi:7b"]):
        with patch.dict("os.environ", {"OLLAMA_URL": "http://localhost:11434", "CHIPSUTRA_PREFER_7B": "true"}):
            r = llm_router.resolve_model(
                provider="ollama",
                requested_model="chipsutra-vlsi:7b",
                model_tier="14b_preferred",
                ollama_url="http://localhost:11434",
            )
    assert r["model"] == "chipsutra-vlsi:14b"
    assert r["reason"] == "tier_14b_available"


def test_resolve_falls_back_7b_when_14b_missing():
    with patch.object(llm_router, "_installed_names", return_value=["chipsutra-vlsi:7b"]):
        with patch.dict("os.environ", {"OLLAMA_URL": "http://localhost:11434", "CHIPSUTRA_PREFER_7B": "true"}):
            r = llm_router.resolve_model(
                provider="ollama",
                requested_model="chipsutra-vlsi:7b",
                model_tier="14b_preferred",
                ollama_url="http://localhost:11434",
            )
    assert r["model"] == "chipsutra-vlsi:7b"
