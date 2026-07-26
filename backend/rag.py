"""
Lightweight RAG for ChipSutra generation (no vector DB, no extra deps).

Loads markdown-ish chunks from backend/knowledge/ and retrieves by keyword overlap.
Disable with RAG_ENABLED=false.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

try:  # optional: vector/embedding reranking. Keyword retrieval works without it.
    import rag_vector
except Exception:  # pragma: no cover - module absent or broken import
    rag_vector = None  # type: ignore[assignment]

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

# Not RAG corpus (Modelfile authoring / internal)
_SKIP_KNOWLEDGE_FILES = frozenset({"vlsi_system.txt", "readme.txt"})

# Boost retrieval when module or filenames hint at a domain
MODULE_HINTS: dict[str, tuple[str, ...]] = {
    "testbench": ("uvm", "sequence", "driver", "monitor", "scoreboard", "agent", "verilator"),
    "assertions": ("sva", "assert", "property", "formal", "handshake"),
    "checkers": ("checker", "scoreboard", "protocol"),
    "covergroups": ("coverage", "bin", "cross", "covergroup"),
    "debug": ("uvm_error", "simulation", "debug", "log", "timeout", "x propagation", "verilator"),
    "coverage_holes": ("coverage", "bin", "cross", "hole", "sequence"),
    "formal_hints": ("sva", "assume", "cover", "formal"),
}

PROTOCOL_ALIASES: dict[str, tuple[str, ...]] = {
    "can": ("can", "can-fd", "bus-off", "can_ip", "iso 11898"),
    "lin": ("lin", "lin bus"),
    "flexray": ("flexray", "tdma"),
    "axi": ("axi", "axi4", "axi-lite", "axilite", "valid", "ready", "awvalid"),
    "ace": ("ace", "ace-lite", "snoop", "coherency"),
    "chi": ("chi", "amba chi", "flit"),
    "apb": ("apb", "psel", "penable", "pready"),
    "ahb": ("ahb", "htrans", "hready", "hburst"),
    "axis": ("axis", "axi-stream", "axi stream", "tvalid", "tlast"),
    "wishbone": ("wishbone", "wbm", "wbs", "cyc", "stb"),
    "avalon": ("avalon", "waitrequest", "readdatavalid"),
    "tilelink": ("tilelink", "tl-ul", "tl-uh", "tl-c"),
    "pcie": ("pcie", "tlp", "completion", "ltssm"),
    "cxl": ("cxl", "cxl.io", "cxl.cache"),
    "ethernet": ("ethernet", "rgmii", "gmii", "mii", "mdio", "mac", "pcs"),
    "ddr": ("ddr", "lpddr", "hbm", "memory controller", "dfi"),
    "sram": ("sram", "rf ", "byte enable", "ecc"),
    "i2c": ("i2c", "sda", "scl", "smbus"),
    "i3c": ("i3c", "ccc", "ibi"),
    "spi": ("spi", "cpol", "cpha", "qspi", "flash"),
    "uart": ("uart", "baud", "usart"),
    "i2s": ("i2s", "tdm", "pdm", "audio"),
    "usb": ("usb", "utmi", "ulpi", "ltssm"),
    "mipi": ("mipi", "csi", "dsi", "d-phy"),
    "jtag": ("jtag", "tap", "tdi", "tdo", "tms", "boundary scan"),
    "swd": ("swd", "swclk", "swdio"),
    "dft": ("dft", "scan", "mbist", "lbist", "atpg", "occ"),
    "cdc": ("cdc", "async fifo", "metastability", "2ff", "rdc"),
    "upf": ("upf", "power domain", "isolation", "retention"),
    "ucie": ("ucie", "bow", "chiplet", "die-to-die", "aib"),
    "riscv": ("risc-v", "riscv", "plic", "clint", "pmp"),
    "uvm": ("uvm", "uvm_env", "sequence", "ral", "scoreboard"),
}


def _enabled() -> bool:
    return os.environ.get("RAG_ENABLED", "true").lower() in ("1", "true", "yes")


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_\-/]{3,}", (text or "").lower()))


def load_chunks(knowledge_dir: Optional[Path] = None) -> List[dict]:
    """Parse ## sections from .txt files in knowledge_dir."""
    root = knowledge_dir or KNOWLEDGE_DIR
    if not root.is_dir():
        return []
    chunks: List[dict] = []
    for path in sorted(root.glob("*.txt")):
        if path.name.lower() in _SKIP_KNOWLEDGE_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        parts = re.split(r"(?m)^##\s+", text)
        if len(parts) <= 1:
            chunks.append({"source": path.name, "title": path.stem, "body": text.strip()})
            continue
        for part in parts[1:]:
            lines = part.strip().splitlines()
            title = lines[0].strip() if lines else path.stem
            body = "\n".join(lines[1:]).strip()
            if body:
                chunks.append({"source": path.name, "title": title, "body": body})
    return chunks


def _score_chunk(query_tokens: set[str], chunk: dict, extra_terms: Sequence[str], protocol_terms: Sequence[str]) -> float:
    blob = f"{chunk['title']} {chunk['body']}".lower()
    ctoks = _tokenize(blob)
    if not ctoks:
        return 0.0
    overlap = len(query_tokens & ctoks)
    for term in protocol_terms:
        if term.lower() in blob:
            overlap += 6
    for term in extra_terms:
        if term.lower() in blob:
            # Module hints only lightly boost unless also in the user query
            overlap += 2 if term.lower() in query_tokens else 1
    return overlap - (len(chunk["body"]) / 8000.0)


def _hybrid_rerank(
    chunks: Sequence[dict],
    query: str,
    scores: Sequence[float],
    top_k: int,
) -> Optional[List[dict]]:
    """Blend keyword scores with embedding similarity; None when vector RAG is unavailable."""
    if rag_vector is None:
        return None
    try:
        if rag_vector.vector_backend() == "disabled":
            return None
        keyword_scores = {i: s for i, s in enumerate(scores) if s > 0}
        hits = rag_vector.hybrid_search(list(chunks), query, keyword_scores=keyword_scores, top_k=top_k)
    except Exception:
        return None
    return hits or None


def retrieve(
    query: str,
    *,
    module: str = "",
    filenames: Optional[Iterable[str]] = None,
    top_k: int = 4,
    knowledge_dir: Optional[Path] = None,
) -> List[dict]:
    chunks = load_chunks(knowledge_dir)
    if not chunks:
        return []
    q = " ".join(filter(None, [query, module, " ".join(filenames or [])]))
    qtok = _tokenize(q)
    extra: List[str] = list(MODULE_HINTS.get(module, ()))
    protocol_terms: List[str] = []
    combined = q.lower()
    for _key, aliases in PROTOCOL_ALIASES.items():
        if any(a in combined for a in aliases):
            protocol_terms.extend(aliases)
    scores = [_score_chunk(qtok, c, extra, protocol_terms) for c in chunks]
    out = _hybrid_rerank(chunks, q, scores, top_k)
    if out is None:
        scored = list(zip(scores, chunks))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [c for s, c in scored if s > 0][:top_k]
    if not out and chunks:
        # Fallback: first section (bus cheat-sheet) for generate calls with no keywords
        out = chunks[: min(2, len(chunks))]
    return out


def format_context(chunks: Sequence[dict]) -> str:
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        parts.append(f"### {c['title']} ({c['source']})\n{c['body']}")
    return "\n\n".join(parts)


def augment_generation_context(
    *,
    module: str,
    prompt: str,
    filenames: Optional[Iterable[str]] = None,
    top_k: int = 4,
) -> str:
    if not _enabled():
        return ""
    chunks = retrieve(prompt, module=module, filenames=filenames, top_k=top_k)
    return format_context(chunks)


def rag_status() -> dict:
    root = KNOWLEDGE_DIR
    chunks = load_chunks(root)
    vector: dict = {"enabled": False, "backend": "disabled", "note": "rag_vector unavailable"}
    if rag_vector is not None:
        try:
            vector = rag_vector.rag_vector_status()
        except Exception as e:
            vector = {"enabled": False, "backend": "disabled", "note": f"rag_vector error: {e}"}
    return {
        "enabled": _enabled(),
        "knowledge_dir": str(root),
        "chunk_count": len(chunks),
        "sources": sorted({c["source"] for c in chunks}),
        "vector": vector,
    }
