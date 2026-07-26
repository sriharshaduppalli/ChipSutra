"""Deeper CDC checks on RTL text (v2) — reconvergence, multi-bit, glitch, depth.

Complements cdc.py (v0 regex crossings) and cdc_netlist.py (Yosys structural)
with the structural mistakes those two miss. Still pure text analysis: no
elaboration, no constraint files, no vendor CDC engine. Experimental.

Output matches cdc.analyze_rtl_texts(): clocks, findings, counts, engine,
disclaimer — plus a "checks" summary of which checks ran.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

ENGINE = "chipsutra-cdc-deep"
DISCLAIMER = (
    "Experimental deep CDC text analysis (reconvergence / multi-bit / glitch / depth) — "
    "heuristic only, not a Spyglass/Questa CDC sign-off replacement."
)

_POSEDGE = re.compile(r"always(?:_ff|_latch)?\s*@\s*\(\s*(?:posedge|negedge)\s+(\w+)", re.I)
_NB_ASSIGN = re.compile(r"(\w+)\s*<=\s*([^;]+);")
_CONT_ASSIGN = re.compile(r"\bassign\s+(\w+)\s*(?:\[[^\]]*\])?\s*=\s*([^;]+);", re.I)
_VECTOR_DECL = re.compile(
    r"\b(?:input|output|inout|reg|wire|logic|bit|var)\b[^;\n=]*?\[[^\]]+\]\s*"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)",
    re.I,
)
_BARE_ID = re.compile(r"^\s*([A-Za-z_]\w*)\s*$")
_LITERAL = re.compile(r"\d*'[sS]?[bodhBODH]?[0-9a-fA-FxXzZ_]+")
_OPERATORS = re.compile(r"[&|^~+\-*/%?:<>!]|\{")

_SCHEME_PATTERNS = (
    (re.compile(r"\basync_?fifo\b|\bafifo\b", re.I), "async FIFO"),
    (re.compile(r"\bgray\b|\bgry\b|\bbin2gray\b|\bgray2bin\b|_gray\b|gray_", re.I), "gray code"),
    (re.compile(r"\bhandshake\b|\bxpm_cdc\b", re.I), "handshake / vendor CDC macro"),
)
_REQ = re.compile(r"\b\w*_?req\w*\b", re.I)
_ACK = re.compile(r"\b\w*_?ack\w*\b", re.I)

_KEYWORDS = {
    "begin", "end", "if", "else", "case", "endcase", "default", "posedge",
    "negedge", "or", "and", "not", "xor", "assign", "always", "always_ff",
    "always_comb", "always_latch", "wire", "reg", "logic", "bit", "signed",
    "unsigned", "function", "endfunction", "return", "for", "while", "begin_",
}
_DECL_KEYWORDS = {"input", "output", "inout", "var", "signed", "unsigned"}
_RESETS = re.compile(r"^(?:a?rst|reset|resetn|rst_n|arstn|aresetn|nreset)$", re.I)
_CLOCKISH = re.compile(r"^(?:clk|clock|aclk|hclk|pclk)\w*$", re.I)


def _identifiers(expr: str) -> List[str]:
    """Identifiers in an expression, minus literals, keywords and reset/clock names."""
    cleaned = _LITERAL.sub(" ", expr)
    out: List[str] = []
    for name in re.findall(r"\b([A-Za-z_]\w*)\b", cleaned):
        if name in _KEYWORDS or _RESETS.match(name) or _CLOCKISH.match(name):
            continue
        if name not in out:
            out.append(name)
    return out


def _is_expression(rhs: str) -> bool:
    """True when the RHS is combinational logic rather than a bare signal."""
    if _BARE_ID.match(rhs):
        return False
    stripped = _LITERAL.sub(" ", rhs)
    return bool(_OPERATORS.search(stripped)) or len(_identifiers(rhs)) > 1


def _scheme_hits(text: str) -> List[str]:
    hits = []
    for pattern, label in _SCHEME_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    if _REQ.search(text) and _ACK.search(text):
        hits.append("req/ack handshake")
    return hits


def _finding(fname: str, signal: str, from_domain: str, to_domain: str, source: str,
             severity: str, kind: str, note: str) -> dict:
    return {
        "filename": fname,
        "signal": signal,
        "from_domain": from_domain,
        "to_domain": to_domain,
        "source": source,
        "severity": severity,
        "kind": kind,
        "note": note,
    }


def _counts(findings: Sequence[dict]) -> Dict[str, int]:
    """cdc_* kinds fold into cdc_warn/cdc_info by severity; rdc counted separately."""
    warn = info = rdc = 0
    for f in findings:
        kind = str(f.get("kind") or "")
        if kind == "rdc":
            rdc += 1
            continue
        if not kind.startswith("cdc"):
            continue
        if f.get("severity") == "warn":
            warn += 1
        elif f.get("severity") == "info":
            info += 1
    return {"cdc_warn": warn, "cdc_info": info, "rdc": rdc}


def _dedupe(findings: Sequence[dict]) -> List[dict]:
    uniq: List[dict] = []
    seen: Set[tuple] = set()
    for f in findings:
        key = (
            f.get("filename"),
            f.get("signal"),
            f.get("from_domain"),
            f.get("to_domain"),
            f.get("kind"),
            f.get("note"),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


class _FileModel:
    """Flop assignments, continuous assignments, vector decls and domains of one file."""

    def __init__(self, fname: str, text: str):
        self.fname = fname
        self.text = text
        self.clocks: Set[str] = set()
        self.vectors: Set[str] = set()
        self.domain: Dict[str, str] = {}
        # (dst, rhs, clk)
        self.flop_assigns: List[Tuple[str, str, str]] = []
        self.cont_assigns: List[Tuple[str, str]] = []
        self._parse()

    def _parse(self) -> None:
        for m in _VECTOR_DECL.finditer(self.text):
            for name in m.group(1).split(","):
                name = name.strip()
                if name and name not in _KEYWORDS and name not in _DECL_KEYWORDS:
                    self.vectors.add(name)

        for block in re.split(r"(?=always(?:_ff|_latch|_comb)?\s*@)", self.text, flags=re.I):
            cm = _POSEDGE.search(block)
            if not cm:
                continue
            clk = cm.group(1)
            self.clocks.add(clk)
            body = block[cm.end():]
            for am in _NB_ASSIGN.finditer(body):
                dst, rhs = am.group(1), am.group(2).strip()
                if dst in _KEYWORDS:
                    continue
                self.flop_assigns.append((dst, rhs, clk))
                self.domain.setdefault(dst, clk)

        for cm2 in _CONT_ASSIGN.finditer(self.text):
            self.cont_assigns.append((cm2.group(1), cm2.group(2).strip()))

    def is_vector(self, name: str) -> bool:
        return name in self.vectors

    def readers_of(self, signal: str, clk: str) -> List[str]:
        """Flops in domain `clk` whose D is exactly `signal` (next synchronizer stage)."""
        return [d for d, rhs, c in self.flop_assigns if c == clk and _BARE_ID.match(rhs) and rhs.strip() == signal]


def analyze_deep(files: List[Tuple[str, str]]) -> dict:
    """Deep CDC checks over (filename, text) pairs; cdc.analyze_rtl_texts() schema."""
    findings: List[dict] = []
    clocks: Set[str] = set()
    per_check: Dict[str, int] = {
        "reconvergence": 0,
        "multibit": 0,
        "glitch": 0,
        "sync_depth": 0,
        "scheme": 0,
    }

    for fname, text in files or []:
        if not text:
            continue
        model = _FileModel(fname, text)
        clocks |= model.clocks
        scheme_hits = _scheme_hits(text)

        # synced output signal -> (original source, source domain, dest domain)
        synced: Dict[str, Tuple[str, str, str]] = {}

        for dst, rhs, clk in model.flop_assigns:
            cross_sources = [
                s for s in _identifiers(rhs)
                if s != dst and model.domain.get(s) and model.domain[s] != clk
            ]
            if not cross_sources:
                continue
            src = cross_sources[0]
            src_domain = model.domain[src]

            if _is_expression(rhs):
                # Check 3: combinational logic ahead of the first synchronizer flop.
                findings.append(_finding(
                    fname, dst, src_domain, clk, ", ".join(cross_sources), "warn", "cdc_glitch",
                    "Combinational logic on cross-domain data feeds the first synchronizer flop — "
                    "glitches can be captured; register in the source domain before crossing",
                ))
                per_check["glitch"] += 1
                continue

            # Bare cross-domain capture: measure the synchronizer chain depth.
            chain = [dst]
            cursor = dst
            while True:
                nxt = [r for r in model.readers_of(cursor, clk) if r not in chain]
                if not nxt:
                    break
                cursor = nxt[0]
                chain.append(cursor)
            depth = len(chain)
            for stage in chain:
                synced[stage] = (src, src_domain, clk)

            if depth < 2:
                # Check 4: one flop only — insufficient MTBF for a control crossing.
                findings.append(_finding(
                    fname, dst, src_domain, clk, src, "warn", "cdc_1ff",
                    "Single-flop capture of a cross-domain signal — use at least a 2FF "
                    "synchronizer (3FF for high-frequency / high-MTBF targets)",
                ))
                per_check["sync_depth"] += 1

            # Check 2: buses cannot cross on a bit-parallel flop synchronizer.
            if model.is_vector(src) and not scheme_hits:
                findings.append(_finding(
                    fname, dst, src_domain, clk, src, "warn", "cdc_multibit",
                    f"Multi-bit signal '{src}' crossing through a {depth}FF flop synchronizer — "
                    "bits can settle on different cycles; use gray coding, an async FIFO or a handshake",
                ))
                per_check["multibit"] += 1

        # Check 1: two crossings from the same source domain recombined downstream.
        expressions: List[Tuple[str, str]] = [(d, r) for d, r, _c in model.flop_assigns]
        expressions += model.cont_assigns
        for dst, rhs in expressions:
            groups: Dict[Tuple[str, str], List[str]] = {}
            for name in _identifiers(rhs):
                entry = synced.get(name)
                if not entry or name == dst:
                    continue
                src, src_domain, dst_domain = entry
                groups.setdefault((src_domain, dst_domain), [])
                if src not in groups[(src_domain, dst_domain)]:
                    groups[(src_domain, dst_domain)].append(src)
            for (src_domain, dst_domain), srcs in groups.items():
                if len(srcs) < 2:
                    continue
                findings.append(_finding(
                    fname, dst, src_domain, dst_domain, ", ".join(sorted(srcs)), "warn", "cdc_reconvergence",
                    "Reconvergence: separately synchronized signals from the same source domain are "
                    "recombined — they may settle on different cycles; synchronize as one vector "
                    "(gray/FIFO) or add a qualifying handshake",
                ))
                per_check["reconvergence"] += 1

        # Check 5: recognized CDC schemes, reported as informational credit.
        for label in scheme_hits:
            findings.append(_finding(
                fname, label.replace(" ", "_"), "n/a", "n/a", label, "info", "cdc_scheme",
                f"Recognized CDC scheme ({label}) — structure looks intentional; "
                "verify depth and constraints manually",
            ))
            per_check["scheme"] += 1

    uniq = _dedupe(findings)
    return {
        "clocks": sorted(clocks),
        "findings": uniq[:200],
        "counts": _counts(uniq),
        "engine": ENGINE,
        "disclaimer": DISCLAIMER,
        "checks": {name: {"ran": True, "findings": n} for name, n in per_check.items()},
    }


def merge_deep(base: dict, deep: Optional[dict]) -> dict:
    """Union a baseline CDC result (cdc.py / cdc_netlist.py) with deep findings."""
    if not deep:
        return base or {}
    if not base:
        base = {}
    findings = list(base.get("findings") or []) + list(deep.get("findings") or [])
    uniq = _dedupe(findings)
    engines = [e for e in (base.get("engine"), deep.get("engine")) if e]
    merged = {
        "clocks": sorted(set(base.get("clocks") or []) | set(deep.get("clocks") or [])),
        "findings": uniq[:200],
        "counts": _counts(uniq),
        "engine": "chipsutra-cdc-deep-merged",
        "disclaimer": DISCLAIMER,
        "engines": engines,
    }
    if deep.get("checks"):
        merged["checks"] = deep["checks"]
    return merged
