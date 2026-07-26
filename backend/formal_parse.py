"""Parse SymbiYosys / smtbmc logs and locate counterexample traces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


_PROP = re.compile(
    r"(?P<status>PASS|FAIL|UNKNOWN|ERROR|TIMEOUT)\s*(?:\[[^\]]*\])?\s*(?P<name>[A-Za-z0-9_.:/<>\-]+)?",
    re.IGNORECASE,
)


def parse_sby_log(text: str) -> List[Dict[str, str]]:
    props: List[Dict[str, str]] = []
    seen = set()
    for line in (text or "").splitlines():
        # Common forms: "Assert failed", "Status: PASS", "BMC failed", "Reached cover"
        m = re.search(r"\b(PASS|FAIL|UNKNOWN)\b", line, re.I)
        if not m:
            continue
        status = m.group(1).upper()
        name = "property"
        nm = re.search(r"(assert|assume|cover|property)\s+([A-Za-z_][\w.]*)", line, re.I)
        if nm:
            name = nm.group(2)
        else:
            # trailing token
            toks = re.findall(r"[A-Za-z_][\w.]*", line)
            if toks:
                name = toks[-1]
        key = (status, name, line.strip()[:80])
        if key in seen:
            continue
        seen.add(key)
        props.append({"name": name, "status": status, "detail": line.strip()[:200]})
    return props[:100]


def find_cex_vcds(work_dir: str | Path) -> List[Path]:
    root = Path(work_dir)
    hits: List[Path] = []
    for pat in ("**/trace*.vcd", "**/*cex*.vcd", "**/engine*/**/*.vcd"):
        hits.extend(root.glob(pat))
    # unique by resolved path
    uniq = []
    seen = set()
    for p in hits:
        rp = str(p.resolve())
        if rp in seen:
            continue
        if p.is_file() and p.stat().st_size > 0:
            seen.add(rp)
            uniq.append(p)
    return uniq
