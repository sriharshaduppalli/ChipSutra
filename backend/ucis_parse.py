"""Industry coverage format adapters (UCIS XML, Synopsys URG / Cadence IMC text, CSV).

Stdlib only. Every parser returns the standard coverage summary schema used by
``coverage_parse``: ``{overall, metrics, holes, count, source}``.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

HOLE_THRESHOLD = 90.0
_MAX_METRICS = 80
_MAX_HOLES = 40

# UCIS scopes we understand (compared against the namespace-stripped tag, lowercased)
_UCIS_TAGS = {
    "coverageinstance",
    "covergroup",
    "coverpoint",
    "cross",
    "statement",
    "branch",
    "toggle",
    "fsm",
}

_NAME_ATTRS = ("name", "moduleName", "instanceName", "alias", "key", "id")
_PCT_ATTRS = ("pct", "percent", "percentage", "coverage", "score", "coveragePct")
_COVERED_TOTAL_ATTRS = (
    ("coveredBins", "totalBins"),
    ("covered", "total"),
    ("coveredCount", "totalCount"),
    ("hitCount", "binCount"),
    ("num", "denom"),
)


def _local(tag: object) -> str:
    """Strip the XML namespace from a tag: '{urn:ucis}covergroup' -> 'covergroup'."""
    text = str(tag or "")
    if "}" in text:
        text = text.rsplit("}", 1)[1]
    return text.strip()


def _attr_map(elem: ET.Element) -> Dict[str, str]:
    """Namespace-stripped, lowercased attribute lookup."""
    return {_local(k).lower(): (v or "") for k, v in (elem.attrib or {}).items()}


def _to_float(value: object) -> Optional[float]:
    try:
        num = float(str(value).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return num


def _clamp_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(max(0.0, min(100.0, value)), 1)


def _bins_of(elem: ET.Element) -> Tuple[int, int]:
    """Count (covered, total) from child bin elements carrying hit counts."""
    covered = total = 0
    for child in elem.iter():
        if child is elem:
            continue
        name = _local(child.tag).lower()
        if "bin" not in name:
            continue
        attrs = _attr_map(child)
        raw = None
        for key in ("hits", "count", "hitcount", "value", "coverage"):
            if key in attrs:
                raw = attrs[key]
                break
        if raw is None and (child.text or "").strip():
            raw = (child.text or "").strip()
        hits = _to_float(raw)
        if hits is None:
            continue
        total += 1
        if hits > 0:
            covered += 1
    return covered, total


def _pct_of(elem: ET.Element) -> Tuple[Optional[float], Optional[int], Optional[int]]:
    """Best-effort per-item percentage plus (covered, total) bin counts when known."""
    attrs = _attr_map(elem)

    for key in _PCT_ATTRS:
        val = _to_float(attrs.get(key.lower()))
        if val is not None:
            return _clamp_pct(val), None, None

    for cov_key, tot_key in _COVERED_TOTAL_ATTRS:
        cov = _to_float(attrs.get(cov_key.lower()))
        tot = _to_float(attrs.get(tot_key.lower()))
        if cov is not None and tot is not None and tot > 0:
            return _clamp_pct(100.0 * cov / tot), int(cov), int(tot)

    hits = _to_float(attrs.get("hits"))
    goal = _to_float(attrs.get("goal") or attrs.get("at_least") or attrs.get("atleast"))
    if hits is not None and goal is not None and goal > 0:
        return _clamp_pct(100.0 * min(hits, goal) / goal), None, None
    if hits is not None:
        return (100.0 if hits > 0 else 0.0), None, None

    cov, tot = _bins_of(elem)
    if tot > 0:
        return _clamp_pct(100.0 * cov / tot), cov, tot
    return None, None, None


def _name_of(elem: ET.Element, kind: str, index: int) -> str:
    attrs = _attr_map(elem)
    for key in _NAME_ATTRS:
        val = (attrs.get(key.lower()) or "").strip()
        if val:
            return val
    return f"{kind}_{index}"


def _empty(source: str) -> dict:
    return {"overall": 0.0, "metrics": [], "holes": [], "count": 0, "source": source}


def _finalize(metrics: List[dict], source: str, overall: Optional[float] = None, **extra) -> dict:
    metrics = metrics[:_MAX_METRICS]
    if overall is None:
        weights = [float(m.get("weight") or 1.0) for m in metrics]
        wsum = sum(weights)
        if metrics and wsum > 0:
            overall = sum(m["pct"] * w for m, w in zip(metrics, weights)) / wsum
        else:
            overall = 0.0
    holes = [m for m in metrics if m["pct"] < HOLE_THRESHOLD]
    out = {
        "overall": round(float(overall), 1),
        "metrics": metrics,
        "holes": sorted(holes, key=lambda x: x["pct"])[:_MAX_HOLES],
        "count": len(metrics),
        "source": source,
    }
    out.update(extra)
    return out


# ---------------------------------------------------------------- UCIS XML


def parse_ucis_xml(text: str) -> dict:
    """Parse a UCIS / UCISDB-style XML export into the standard summary schema.

    Real UCIS XML is deeply namespaced; this handles the pragmatic subset of
    scopes (covergroup / coverpoint / cross / statement / branch / toggle / fsm
    and coverageInstance wrappers) that tools actually emit.
    """
    if not (text or "").strip():
        raise ValueError("UCIS XML is empty")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed UCIS XML: {exc}") from exc

    metrics: List[dict] = []
    agg_cov = agg_tot = 0
    for index, elem in enumerate(root.iter()):
        kind = _local(elem.tag).lower()
        if kind not in _UCIS_TAGS:
            continue
        pct, cov, tot = _pct_of(elem)
        if pct is None:
            continue
        attrs = _attr_map(elem)
        metric = {"name": _name_of(elem, kind, index), "pct": pct, "kind": kind}
        weight = _to_float(attrs.get("weight"))
        if weight is not None and weight > 0:
            metric["weight"] = weight
        alias = (attrs.get("alias") or "").strip()
        if alias and alias != metric["name"]:
            metric["alias"] = alias
        if cov is not None and tot:
            metric["hit"] = cov
            metric["miss"] = max(0, tot - cov)
            agg_cov += cov
            agg_tot += tot
        metrics.append(metric)

    if not metrics:
        return _empty("ucis_xml")
    overall = 100.0 * agg_cov / agg_tot if agg_tot > 0 else None
    return _finalize(metrics, "ucis_xml", overall)


# ------------------------------------------------------- Synopsys URG / IMC

_URG_COLUMNS = {
    "score",
    "total",
    "line",
    "lines",
    "cond",
    "condition",
    "toggle",
    "fsm",
    "branch",
    "assert",
    "assertion",
    "statement",
    "stmt",
    "block",
    "expr",
    "expression",
    "group",
    "covergroup",
}
_NUM = re.compile(r"^-?\d+(?:\.\d+)?%?$")
_TOTAL_LINE = re.compile(
    r"\b(total|overall|score)\b[^0-9%\n]{0,30}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%", re.IGNORECASE
)
_LABEL_PCT = re.compile(
    r"([A-Za-z][A-Za-z0-9 _\-./\[\]]{1,48}?)\s*[:=]\s*([0-9]{1,3}(?:\.[0-9]+)?)\s*%"
)


def _tokens(line: str) -> List[str]:
    return [t for t in re.split(r"[\s|,]+", line.strip()) if t]


def _is_num(token: str) -> bool:
    return bool(_NUM.match(token))


def parse_imc_urg_text(text: str) -> dict:
    """Parse Synopsys URG / Cadence IMC style summary tables and totals."""
    lines = (text or "").splitlines()
    metrics: List[dict] = []
    seen: Dict[str, dict] = {}
    overall: Optional[float] = None
    header: List[str] = []

    def add(name: str, pct: Optional[float], kind: str = "") -> None:
        pct = _clamp_pct(pct)
        if pct is None or not name:
            return
        key = name.strip().lower()
        metric = {"name": name.strip(), "pct": pct}
        if kind:
            metric["kind"] = kind
        if key in seen:
            seen[key].update(metric)
        else:
            seen[key] = metric
            metrics.append(metric)

    for raw in lines:
        line = raw.strip()
        if not line:
            header = []
            continue

        total = _TOTAL_LINE.search(line)
        if total and "%" in line and not _is_num(_tokens(line)[0]):
            val = _clamp_pct(_to_float(total.group(2)))
            if val is not None and overall is None:
                overall = val

        toks = _tokens(line)
        lowered = [t.strip("%:").lower() for t in toks]

        # Header row: mostly known column names, no numbers.
        known = [t for t in lowered if t in _URG_COLUMNS]
        if len(known) >= 2 and not any(_is_num(t) for t in toks):
            header = lowered
            continue

        # Data row under a header: numbers, optionally with a leading/trailing name.
        if header:
            nums = [t for t in toks if _is_num(t)]
            if nums:
                names = [t for t in toks if not _is_num(t)]
                prefix = names[0] if names else ""
                num_cols = [c for c in header if c not in ("name", "instance", "module")]
                if len(nums) == len(num_cols) or len(nums) == len(header):
                    cols = num_cols if len(nums) == len(num_cols) else header
                    for col, num in zip(cols, nums):
                        val = _to_float(num)
                        label = f"{prefix} {col}".strip() if prefix else col
                        if col in ("score", "total") and prefix == "" and overall is None:
                            overall = _clamp_pct(val)
                        add(label, val, kind=col)
                    continue

        # "Line Coverage: 92.5%" style lines.
        for match in _LABEL_PCT.finditer(line):
            add(match.group(1), _to_float(match.group(2)))

    if not metrics and overall is None:
        return _empty("imc_urg")
    if not metrics and overall is not None:
        return _finalize([{"name": "total coverage", "pct": overall}], "imc_urg", overall)
    return _finalize(metrics, "imc_urg", overall)


# -------------------------------------------------------------------- CSV

_CSV_NAME_HINTS = ("name", "instance", "module", "unit", "file", "hierarchy", "scope", "design")
_CSV_PCT_HINTS = ("pct", "percent", "coverage", "score", "%")


def parse_coverage_csv(text: str) -> dict:
    """Parse a generic CSV with a name column and a percentage column."""
    body = (text or "").strip()
    if not body:
        return _empty("csv")
    try:
        dialect = csv.Sniffer().sniff(body[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    rows = [r for r in csv.reader(io.StringIO(body), delimiter=delimiter) if any(c.strip() for c in r)]
    if not rows:
        return _empty("csv")

    header = [c.strip() for c in rows[0]]
    lowered = [c.lower() for c in header]
    name_idx = pct_idx = None
    for i, col in enumerate(lowered):
        if name_idx is None and any(h in col for h in _CSV_NAME_HINTS):
            name_idx = i
        if pct_idx is None and any(h in col for h in _CSV_PCT_HINTS):
            pct_idx = i
    data = rows[1:] if (name_idx is not None or pct_idx is not None) else rows

    if name_idx is None:
        name_idx = 0
    if pct_idx is None:
        # Last column that parses as a number across the data rows.
        for i in range(len(header) - 1, -1, -1):
            if i == name_idx:
                continue
            if any(_to_float(r[i]) is not None for r in data if i < len(r)):
                pct_idx = i
                break
    if pct_idx is None:
        return _empty("csv")

    metrics: List[dict] = []
    for row in data:
        if pct_idx >= len(row):
            continue
        pct = _clamp_pct(_to_float(row[pct_idx]))
        if pct is None:
            continue
        name = row[name_idx].strip() if name_idx < len(row) else ""
        if not name or name_idx == pct_idx:
            name = f"row_{len(metrics) + 1}"
        metrics.append({"name": name, "pct": pct})

    if not metrics:
        return _empty("csv")
    return _finalize(metrics, "csv")


# ------------------------------------------------------------- auto-detect


def detect_and_parse(text: str, filename: str = "") -> dict:
    """Sniff the coverage format and parse it; raises ValueError if nothing parses."""
    body = text or ""
    if not body.strip():
        raise ValueError("Coverage report is empty")

    lower_name = (filename or "").lower()
    stripped = body.lstrip()
    first_line = next((l for l in body.splitlines() if l.strip()), "")

    looks_xml = stripped.startswith("<?xml") or stripped.startswith("<")
    looks_xml = looks_xml or lower_name.endswith((".xml", ".ucis", ".ucisdb"))
    looks_csv = lower_name.endswith((".csv", ".tsv")) or (
        first_line.count(",") >= 1 and "<" not in first_line
    )

    order: List[Tuple[str, object]] = []
    if looks_xml:
        order.append(("ucis_xml", parse_ucis_xml))
    if looks_csv:
        order.append(("csv", parse_coverage_csv))
    order.append(("imc_urg", parse_imc_urg_text))
    for name, fn in (("ucis_xml", parse_ucis_xml), ("csv", parse_coverage_csv)):
        if name not in [o[0] for o in order]:
            order.append((name, fn))

    errors: List[str] = []
    for name, fn in order:
        try:
            result = fn(body)  # type: ignore[operator]
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue
        if result.get("count"):
            result["detected"] = name
            return result

    detail = f" ({'; '.join(errors)})" if errors else ""
    raise ValueError(f"Unrecognized coverage format: no metrics parsed{detail}")
