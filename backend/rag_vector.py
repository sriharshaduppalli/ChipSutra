"""
Vector/embedding RAG for ChipSutra — optional deps, always works offline.

Complements the keyword retriever in `rag.py`. Two backends are tried in order:

1. `sentence-transformers` — only if the package imports AND `RAG_VECTOR_BACKEND`
   allows it (`auto` default, or `sentence-transformers`).
2. `hashed-tfidf` — pure-stdlib fallback: hashed word + character n-gram TF-IDF
   vectors with the signed hashing trick. Deterministic, no downloads.

Disable entirely with `RAG_VECTOR_ENABLED=false` (then `hybrid_search` degrades to
keyword-only ordering). Tune with `RAG_VECTOR_DIM` and `RAG_VECTOR_MODEL`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional, Sequence

DEFAULT_DIM = 512
DEFAULT_ST_MODEL = "all-MiniLM-L6-v2"

_NGRAM = 3
# Character n-grams give fuzzy matching (fifos ~ fifo) but must not drown out whole words.
_NGRAM_WEIGHT = 0.35
_MIN_NGRAM_TOKEN = 4

_WORD_RE = re.compile(r"[a-z0-9_]{2,}")

# Populated lazily; keyed by a hash of the chunk bodies so repeated calls are cheap.
_INDEX_CACHE: Dict[str, dict] = {}
_ST_MODEL = None
_ST_FAILED = False
_NOTE = ""


# =========================
# Backend selection
# =========================
def _enabled() -> bool:
    return os.environ.get("RAG_VECTOR_ENABLED", "true").lower() in ("1", "true", "yes")


def _preference() -> str:
    pref = os.environ.get("RAG_VECTOR_BACKEND", "auto").strip().lower()
    if pref in ("st", "sbert", "sentence_transformers", "sentence-transformers"):
        return "sentence-transformers"
    if pref in ("hashed", "hashed-tfidf", "tfidf", "fallback"):
        return "hashed-tfidf"
    return "auto"


def _st_available() -> bool:
    if _ST_FAILED:
        return False
    try:
        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:
        return False


def vector_backend() -> str:
    """"sentence-transformers" | "hashed-tfidf" | "disabled"."""
    if not _enabled():
        return "disabled"
    pref = _preference()
    if pref in ("auto", "sentence-transformers") and _st_available():
        return "sentence-transformers"
    return "hashed-tfidf"


def _hashed_dim() -> int:
    try:
        dim = int(os.environ.get("RAG_VECTOR_DIM", DEFAULT_DIM))
    except ValueError:
        dim = DEFAULT_DIM
    return max(32, dim)


def _load_st_model():
    """Load (and cache) the sentence-transformers model, or None if it fails."""
    global _ST_MODEL, _ST_FAILED, _NOTE
    if _ST_MODEL is not None or _ST_FAILED:
        return _ST_MODEL
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _ST_MODEL = SentenceTransformer(os.environ.get("RAG_VECTOR_MODEL", DEFAULT_ST_MODEL))
    except Exception as e:  # offline / missing weights / broken install
        _ST_FAILED = True
        _NOTE = f"sentence-transformers unavailable ({e}); using hashed-tfidf"
        _ST_MODEL = None
    return _ST_MODEL


def embedding_dim() -> int:
    backend = vector_backend()
    if backend == "disabled":
        return 0
    if backend == "sentence-transformers":
        model = _load_st_model()
        if model is not None:
            try:
                return int(model.get_sentence_embedding_dimension())
            except Exception:
                pass
    return _hashed_dim()


# =========================
# Hashed TF-IDF fallback
# =========================
def _features(text: str) -> List[str]:
    feats: List[str] = []
    for tok in _WORD_RE.findall((text or "").lower()):
        feats.append("w:" + tok)
        if len(tok) >= _MIN_NGRAM_TOKEN:
            padded = f"#{tok}#"
            for i in range(len(padded) - _NGRAM + 1):
                feats.append("g:" + padded[i : i + _NGRAM])
    return feats


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    h = int.from_bytes(hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest(), "big")
    return h % dim, (1.0 if (h // dim) % 2 == 0 else -1.0)


def _build_idf(texts: Sequence[str]) -> tuple[Dict[str, float], float]:
    n = max(1, len(texts))
    df: Counter = Counter()
    for t in texts:
        df.update(set(_features(t)))
    idf = {feat: math.log((n + 1.0) / (c + 1.0)) + 1.0 for feat, c in df.items()}
    return idf, math.log(n + 1.0) + 1.0


def _l2(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


def _vectorize(text: str, idf: Dict[str, float], default_idf: float, dim: int) -> List[float]:
    vec = [0.0] * dim
    for feat, tf in Counter(_features(text)).items():
        weight = (1.0 + math.log(tf)) * idf.get(feat, default_idf)
        if feat.startswith("g:"):
            weight *= _NGRAM_WEIGHT
        pos, sign = _bucket(feat, dim)
        vec[pos] += sign * weight
    return _l2(vec)


# =========================
# Public embedding API
# =========================
def embed(texts: List[str]) -> List[List[float]]:
    """Embed texts with the active backend. Vectors are L2-normalized.

    For `hashed-tfidf` the IDF is derived from the supplied batch, so the result is
    deterministic for a given input list. Returns empty vectors when disabled.
    """
    texts = list(texts or [])
    if not texts:
        return []
    backend = vector_backend()
    if backend == "disabled":
        return [[] for _ in texts]
    if backend == "sentence-transformers":
        model = _load_st_model()
        if model is not None:
            try:
                raw = model.encode(texts, show_progress_bar=False)
                return [_l2([float(v) for v in row]) for row in raw]
            except Exception as e:
                global _NOTE
                _NOTE = f"sentence-transformers encode failed ({e}); using hashed-tfidf"
    dim = _hashed_dim()
    idf, default_idf = _build_idf(texts)
    return [_vectorize(t, idf, default_idf, dim) for t in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; safe for empty/zero/mismatched-length vectors."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(a[i] * a[i] for i in range(n)))
    nb = math.sqrt(sum(b[i] * b[i] for i in range(n)))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


# =========================
# Index + search
# =========================
def _chunk_text(chunk: dict) -> str:
    return f"{chunk.get('title', '')}\n{chunk.get('body', '')}".strip()


def _cache_key(chunks: Sequence[dict], backend: str, dim: int) -> str:
    h = hashlib.sha256()
    h.update(f"{backend}|{dim}|".encode("utf-8"))
    for c in chunks:
        h.update(_chunk_text(c).encode("utf-8", errors="ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def build_index(chunks: List[dict]) -> dict:
    """Embed `rag.load_chunks`-shaped chunks. Cached by chunk-body hash."""
    chunks = list(chunks or [])
    backend = vector_backend()
    dim = embedding_dim()
    key = _cache_key(chunks, backend, dim)
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached

    texts = [_chunk_text(c) for c in chunks]
    index: dict = {"vectors": [], "chunks": chunks, "backend": backend, "dim": dim}
    if backend == "disabled" or not chunks:
        _INDEX_CACHE[key] = index
        return index

    if backend == "hashed-tfidf":
        idf, default_idf = _build_idf(texts)
        index["idf"] = idf
        index["idf_default"] = default_idf
        index["vectors"] = [_vectorize(t, idf, default_idf, dim) for t in texts]
    else:
        index["vectors"] = embed(texts)
        # embed() may have degraded to the fallback; keep the index honest.
        if index["vectors"] and len(index["vectors"][0]) != dim:
            index["dim"] = len(index["vectors"][0])
            index["backend"] = vector_backend()
    _INDEX_CACHE[key] = index
    return index


def _query_vector(index: dict, query: str) -> List[float]:
    if index.get("backend") == "disabled":
        return []
    if "idf" in index:
        return _vectorize(query, index["idf"], index.get("idf_default", 1.0), index.get("dim") or _hashed_dim())
    vecs = embed([query])
    return vecs[0] if vecs else []


def search(index: dict, query: str, top_k: int = 4) -> List[dict]:
    """Rank indexed chunks against `query`; returns copies with a "score" key."""
    vectors = index.get("vectors") or []
    chunks = index.get("chunks") or []
    if not vectors or not chunks:
        return []
    qv = _query_vector(index, query)
    if not qv:
        return []
    scored = [(cosine(qv, vectors[i]), c) for i, c in enumerate(chunks) if i < len(vectors)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [dict(c, score=round(float(s), 6)) for s, c in scored[: max(0, top_k)]]


def hybrid_search(
    chunks: List[dict],
    query: str,
    keyword_scores: Optional[Dict[int, float]] = None,
    top_k: int = 4,
) -> List[dict]:
    """Blend vector similarity (0.6) with caller-supplied keyword scores (0.4).

    `keyword_scores` maps a position in `chunks` to a raw keyword score (e.g. from
    `rag._score_chunk`). Both score families are max-normalized before blending so
    the weights mean the same thing regardless of scale.
    """
    chunks = list(chunks or [])
    if not chunks:
        return []
    index = build_index(chunks)
    vectors = index.get("vectors") or []
    qv = _query_vector(index, query)
    vscores = [max(0.0, cosine(qv, vectors[i])) if i < len(vectors) and qv else 0.0 for i in range(len(chunks))]
    kscores = [max(0.0, float((keyword_scores or {}).get(i, 0.0))) for i in range(len(chunks))]

    vmax = max(vscores) or 1.0
    kmax = max(kscores) or 1.0
    have_kw = bool(keyword_scores) and max(kscores) > 0.0
    have_vec = max(vscores) > 0.0
    if have_kw and have_vec:
        w_vec, w_kw = 0.6, 0.4
    elif have_kw:
        w_vec, w_kw = 0.0, 1.0
    else:
        w_vec, w_kw = 1.0, 0.0

    out = []
    for i, c in enumerate(chunks):
        vs = vscores[i] / vmax
        ks = kscores[i] / kmax
        out.append(
            dict(
                c,
                score=round(w_vec * vs + w_kw * ks, 6),
                vector_score=round(vscores[i], 6),
                keyword_score=round(kscores[i], 6),
            )
        )
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[: max(0, top_k)]


def clear_cache() -> None:
    """Drop the index cache (env changes / tests)."""
    _INDEX_CACHE.clear()


def rag_vector_status() -> dict:
    backend = vector_backend()
    status: dict = {
        "enabled": _enabled(),
        "backend": backend,
        "dim": embedding_dim(),
        "note": _NOTE
        or (
            "vector RAG disabled (RAG_VECTOR_ENABLED=false)"
            if backend == "disabled"
            else "hashed char-ngram TF-IDF fallback (stdlib only, no downloads)"
            if backend == "hashed-tfidf"
            else "sentence-transformers embeddings"
        ),
    }
    try:
        from rag import load_chunks

        status["chunk_count"] = len(load_chunks())
    except Exception:
        pass
    return status
