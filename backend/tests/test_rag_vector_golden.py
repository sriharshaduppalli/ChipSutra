"""Vector RAG, rate limiter and golden-DUT fixture tests (no network, no extra deps)."""
import shutil
import subprocess
from pathlib import Path

import pytest

import rag_vector
import rate_limit
from rag_vector import (
    build_index,
    cosine,
    embed,
    hybrid_search,
    rag_vector_status,
    search,
    vector_backend,
)
from rate_limit import (
    check_rate_limit,
    limiter_backend,
    rate_limit_status,
    redis_client,
    reset_rate_limit,
)

GOLDEN = Path(__file__).resolve().parents[1] / "knowledge" / "golden"

CHUNKS = [
    {
        "source": "vlsi_soc_dft_power.txt",
        "title": "CDC and async FIFO",
        "body": (
            "Async FIFO crossings use gray code pointers so only one bit toggles per "
            "increment; synchronize the gray pointer with a 2FF synchronizer in the "
            "destination clock domain and compare pointers to derive full and empty."
        ),
    },
    {
        "source": "vlsi_protocols_compact.txt",
        "title": "I2C bus",
        "body": (
            "I2C uses open-drain SDA and SCL lines with start and stop conditions, a "
            "7-bit address phase and per-byte acknowledge from the addressed target."
        ),
    },
    {
        "source": "vlsi_soc_dft_power.txt",
        "title": "UPF power intent",
        "body": (
            "UPF describes power domains, isolation cells on outputs of shut-down "
            "domains, retention registers and level shifters between voltage areas."
        ),
    },
]

FIFO_QUERY = "async fifo gray code pointer"


@pytest.fixture(autouse=True)
def _clean_state():
    rag_vector.clear_cache()
    reset_rate_limit()
    yield
    rag_vector.clear_cache()
    reset_rate_limit()


# =========================
# Vector backend basics
# =========================
def test_vector_backend_is_available_offline():
    assert vector_backend() in ("sentence-transformers", "hashed-tfidf")


def test_rag_vector_status_shape():
    st = rag_vector_status()
    assert st["enabled"] is True
    assert st["backend"] in ("sentence-transformers", "hashed-tfidf")
    assert st["dim"] > 0
    assert isinstance(st["note"], str) and st["note"]
    if "chunk_count" in st:
        assert st["chunk_count"] >= 0


def test_vector_backend_disabled_by_env(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_ENABLED", "false")
    rag_vector.clear_cache()
    assert vector_backend() == "disabled"
    st = rag_vector_status()
    assert st["enabled"] is False and st["dim"] == 0
    assert search(build_index(CHUNKS), FIFO_QUERY) == []


def test_hashed_backend_forced_by_env(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "hashed-tfidf")
    rag_vector.clear_cache()
    assert vector_backend() == "hashed-tfidf"


# =========================
# Embeddings
# =========================
def test_embed_is_deterministic_and_normalized():
    texts = [c["body"] for c in CHUNKS]
    first = embed(texts)
    second = embed(texts)
    assert first == second
    assert len(first) == len(texts)
    dim = len(first[0])
    assert dim > 0
    for vec in first:
        assert len(vec) == dim
        norm = sum(v * v for v in vec) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-6)


def test_embed_empty_and_blank_inputs():
    assert embed([]) == []
    blank = embed(["", "   "])
    assert len(blank) == 2
    assert all(v == 0.0 for v in blank[0])


def test_cosine_sanity():
    a, b = embed(["gray code pointer async fifo", "gray code pointer async fifo"])
    assert cosine(a, b) == pytest.approx(1.0, abs=1e-6)
    fifo_vec, i2c_vec = embed([CHUNKS[0]["body"], CHUNKS[1]["body"]])
    assert cosine(fifo_vec, i2c_vec) < 0.9
    assert cosine([], [1.0, 2.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0


# =========================
# Index + search
# =========================
def test_build_index_shape_and_cache():
    index = build_index(CHUNKS)
    assert index["backend"] == vector_backend()
    assert index["dim"] > 0
    assert len(index["vectors"]) == len(CHUNKS)
    assert len(index["vectors"][0]) == index["dim"]
    assert build_index(CHUNKS) is index  # cached by chunk-body hash
    assert build_index(CHUNKS[:2]) is not index


def test_search_ranks_fifo_cdc_chunk_above_unrelated():
    hits = search(build_index(CHUNKS), FIFO_QUERY, top_k=3)
    assert len(hits) == 3
    assert hits[0]["title"] == "CDC and async FIFO"
    assert hits[0]["score"] > hits[1]["score"]
    assert hits[0]["score"] > 0.0
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)


def test_search_top_k_and_empty_corpus():
    assert len(search(build_index(CHUNKS), FIFO_QUERY, top_k=1)) == 1
    assert search(build_index([]), FIFO_QUERY) == []


def test_search_matches_other_topics_too():
    hits = search(build_index(CHUNKS), "isolation cells retention power domain", top_k=1)
    assert hits[0]["title"] == "UPF power intent"


# =========================
# Hybrid search
# =========================
def test_hybrid_search_returns_top_k_with_scores():
    hits = hybrid_search(CHUNKS, FIFO_QUERY, top_k=2)
    assert len(hits) == 2
    assert hits[0]["title"] == "CDC and async FIFO"
    for h in hits:
        assert 0.0 <= h["score"] <= 1.0
        assert "vector_score" in h and "keyword_score" in h
        assert h["source"] and h["body"]


def test_hybrid_search_respects_keyword_weighting():
    # Vector alone puts the FIFO chunk first; a dominant keyword score on the I2C
    # chunk (0.4 weight, max-normalized) must be able to overtake it.
    vector_only = hybrid_search(CHUNKS, FIFO_QUERY, top_k=3)
    assert vector_only[0]["title"] == "CDC and async FIFO"

    blended = hybrid_search(CHUNKS, FIFO_QUERY, keyword_scores={1: 100.0}, top_k=3)
    titles = [h["title"] for h in blended]
    assert titles.index("I2C bus") < titles.index("UPF power intent")
    assert blended[[h["title"] for h in blended].index("I2C bus")]["keyword_score"] == 100.0

    # Mild keyword support for the already-best chunk keeps it on top.
    reinforced = hybrid_search(CHUNKS, FIFO_QUERY, keyword_scores={0: 10.0, 1: 1.0}, top_k=3)
    assert reinforced[0]["title"] == "CDC and async FIFO"


def test_hybrid_search_edge_cases():
    assert hybrid_search([], FIFO_QUERY) == []
    assert len(hybrid_search(CHUNKS, "", keyword_scores={2: 5.0}, top_k=1)) == 1
    assert hybrid_search(CHUNKS, "", keyword_scores={2: 5.0}, top_k=1)[0]["title"] == "UPF power intent"


# =========================
# Rate limiting
# =========================
def test_memory_backend_allows_then_blocks():
    key = "test:memory:burst"
    for i in range(5):
        r = check_rate_limit(key, max_calls=5, window_s=60.0)
        assert r["allowed"] is True, f"call {i} should be allowed"
        assert r["remaining"] == 4 - i
    blocked = check_rate_limit(key, max_calls=5, window_s=60.0)
    assert blocked["allowed"] is False
    assert blocked["remaining"] == 0
    assert blocked["reset_in"] > 0.0


def test_memory_window_expiry_and_isolation():
    assert check_rate_limit("test:w", max_calls=1, window_s=0.05)["allowed"] is True
    assert check_rate_limit("test:w", max_calls=1, window_s=0.05)["allowed"] is False
    import time

    time.sleep(0.08)
    assert check_rate_limit("test:w", max_calls=1, window_s=0.05)["allowed"] is True
    # different keys have independent budgets
    assert check_rate_limit("test:other", max_calls=1, window_s=60.0)["allowed"] is True


def test_check_rate_limit_result_shape():
    r = check_rate_limit("test:shape", max_calls=3)
    assert set(["allowed", "remaining", "reset_in", "backend"]).issubset(r)
    assert isinstance(r["allowed"], bool)
    assert isinstance(r["remaining"], int)
    assert isinstance(r["reset_in"], float)
    assert r["backend"] in ("redis", "memory")


def test_limiter_backend_and_status_shape():
    assert limiter_backend() in ("redis", "memory")
    st = rate_limit_status()
    assert st["backend"] in ("redis", "memory")
    assert isinstance(st["redis_url_set"], bool)
    assert isinstance(st["healthy"], bool)


def test_enforce_rate_limit_raises_429():
    from fastapi import HTTPException

    key = "test:enforce"
    rate_limit.enforce_rate_limit(key, max_calls=1, window_s=60.0)
    with pytest.raises(HTTPException) as exc:
        rate_limit.enforce_rate_limit(key, max_calls=1, window_s=60.0)
    assert exc.value.status_code == 429


def test_no_redis_url_means_memory_backend(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    rate_limit.reset_limiter_cache()
    assert redis_client() is None
    assert limiter_backend() == "memory"
    assert rate_limit_status()["redis_url_set"] is False
    rate_limit.reset_limiter_cache()


def test_redis_client_never_raises_on_bad_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")
    rate_limit.reset_limiter_cache()
    assert redis_client() is None  # package missing or connection refused -> None
    r = check_rate_limit("test:badredis", max_calls=2, window_s=60.0)
    assert r["allowed"] is True and r["backend"] == "memory"
    rate_limit.reset_limiter_cache()


@pytest.mark.skipif(redis_client() is None, reason="redis not available")
def test_redis_backend_counts_when_available():
    key = "test:redis:burst"
    reset_rate_limit(key)
    assert check_rate_limit(key, max_calls=2, window_s=5.0)["backend"] == "redis"
    assert check_rate_limit(key, max_calls=2, window_s=5.0)["allowed"] is True
    assert check_rate_limit(key, max_calls=2, window_s=5.0)["allowed"] is False
    reset_rate_limit(key)


# =========================
# Golden DUT fixtures
# =========================
GOLDEN_RTL = ["counter.sv", "fifo.sv", "axi_lite_slave.sv"]
GOLDEN_TB = ["fifo_tb.sv", "axi_lite_slave_tb.sv"]


@pytest.mark.parametrize("name", GOLDEN_RTL + GOLDEN_TB)
def test_golden_files_exist_and_are_valid_modules(name):
    path = GOLDEN / name
    assert path.is_file(), f"missing golden file {name}"
    text = path.read_text(encoding="utf-8")
    assert len(text.strip()) > 200
    assert "module" in text and "endmodule" in text
    assert text.count("module") >= text.count("endmodule")


@pytest.mark.parametrize("name", GOLDEN_TB)
def test_golden_testbenches_are_self_checking(name):
    text = (GOLDEN / name).read_text(encoding="utf-8")
    assert "$dumpfile" in text and "$dumpvars" in text
    assert "TEST PASSED" in text and "TEST FAILED" in text
    assert "$finish" in text


def test_golden_fifo_and_axi_content():
    fifo = (GOLDEN / "fifo.sv").read_text(encoding="utf-8")
    assert "module fifo" in fifo
    assert "always_ff" in fifo and "always_comb" in fifo
    for sig in ("full", "empty", "count", "WIDTH", "DEPTH"):
        assert sig in fifo

    axi = (GOLDEN / "axi_lite_slave.sv").read_text(encoding="utf-8")
    assert "module axi_lite_slave" in axi
    for sig in ("s_axi_awvalid", "s_axi_awready", "s_axi_wvalid", "s_axi_bresp",
                "s_axi_arvalid", "s_axi_rvalid", "s_axi_rresp"):
        assert sig in axi


def test_golden_readme_documents_suite():
    text = (GOLDEN / "README.md").read_text(encoding="utf-8")
    for name in GOLDEN_RTL + GOLDEN_TB:
        assert name in text
    assert "verilator" in text.lower()


@pytest.mark.skipif(not shutil.which("verilator"), reason="verilator not installed")
@pytest.mark.parametrize("name", ["fifo.sv", "axi_lite_slave.sv"])
def test_golden_rtl_verilator_lint(name):
    proc = subprocess.run(
        ["verilator", "--lint-only", "-Wall", str(GOLDEN / name)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
