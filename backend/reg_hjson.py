"""Import OpenTitan / reggen-style HJSON register maps into ChipSutra csr_list.

Does not vendor or invoke OpenTitan ralgen, FuseSoC, or dv_base_reg.
Only named registers in the user file become CSRs — never invent offsets.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_SWACCESS = {
    "rw": "RW",
    "ro": "RO",
    "wo": "WO",
    "r0w1c": "W1C",
    "rw1c": "W1C",
    "rw1s": "RW",
    "rw0c": "W1C",
    "rc": "RC",
    "wr": "RW",
}


def _int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    s = str(val).strip().replace("_", "")
    try:
        return int(s, 0)
    except ValueError:
        return default


def _parse_bits(spec: Any) -> tuple[int, int]:
    """Return (lsb, width) from '7:0', '0', or 3."""
    if spec is None or spec == "":
        return 0, 1
    if isinstance(spec, int):
        return spec, 1
    s = str(spec).strip()
    if ":" in s:
        hi, lo = s.split(":", 1)
        h, l = _int(hi, 0), _int(lo, 0)
        if h < l:
            h, l = l, h
        return l, h - l + 1
    return _int(s, 0), 1


def loads_hjson(text: str) -> Any:
    """JSON first; then a small Hjson subset (comments, bare keys, trailing commas)."""
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    return json.loads(_hjson_to_json(raw))


def load_hjson(path: Union[str, Path]) -> Any:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"HJSON not found: {p}")
    return loads_hjson(p.read_text(encoding="utf-8"))


def _hjson_to_json(text: str) -> str:
    s = text.replace("\r\n", "\n")
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    out: List[str] = []
    i, n = 0, len(s)
    in_str = False
    quote = ""
    while i < n:
        ch = s[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(s[i + 1])
                i += 2
                continue
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in "'\"":
            in_str = True
            quote = ch
            out.append('"')
            i += 1
            continue
        if ch == "#" or (ch == "/" and i + 1 < n and s[i + 1] == "/"):
            while i < n and s[i] != "\n":
                i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (s[j].isalnum() or s[j] in "_-"):
                j += 1
            ident = s[i:j]
            k = j
            while k < n and s[k] in " \t":
                k += 1
            if k < n and s[k] == ":":
                out.append(f'"{ident}"')
                i = j
                continue
            # bare value: rw, ro, true, …
            if ident in ("true", "false", "null"):
                out.append(ident)
            else:
                out.append(json.dumps(ident))
            i = j
            continue
        out.append(ch)
        i += 1
    compact = "".join(out)
    # Hjson uses newlines as separators
    compact = re.sub(
        r'(true|false|null|\d+|"|\}|\])(\s*\n\s*)(?=["{\[])',
        r"\1,\2",
        compact,
    )
    compact = re.sub(r",(\s*[}\]])", r"\1", compact)
    return compact


def _field_reset(field: dict, default: int = 0) -> int:
    if "resval" in field:
        return _int(field.get("resval"), default)
    if "reset" in field:
        return _int(field.get("reset"), default)
    return default


def _fields_from(reg: dict, access: str) -> List[Dict[str, Any]]:
    out = []
    for f in reg.get("fields") or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "").strip()
        if not name:
            continue
        lsb, width = _parse_bits(f.get("bits"))
        facc = _SWACCESS.get(str(f.get("swaccess") or access).lower(), access)
        out.append(
            {
                "name": name,
                "lsb": lsb,
                "width": width,
                "access": facc,
                "reset": _field_reset(f, 0),
            }
        )
    return out


def _reg_reset(reg: dict, fields: List[Dict[str, Any]]) -> int:
    if "resval" in reg:
        return _int(reg.get("resval"), 0)
    val = 0
    for f in fields:
        val |= (int(f.get("reset") or 0) & ((1 << int(f["width"])) - 1)) << int(f["lsb"])
    return val


def registers_from_ip_hjson(doc: Any, *, limit: int = 64) -> List[Dict[str, Any]]:
    """Walk a reggen IP HJSON `registers` list. Offset from file only."""
    if not isinstance(doc, dict):
        return []
    regs = doc.get("registers")
    if not isinstance(regs, list):
        return []
    stride = max(1, _int(doc.get("regwidth"), 32) // 8)
    offset = 0
    out: List[Dict[str, Any]] = []

    def add(name: str, addr: int, access: str, width: int, fields: List[dict], reset: int) -> None:
        if len(out) >= limit:
            return
        out.append(
            {
                "name": name,
                "addr": hex(addr),
                "reset": hex(reset),
                "access": access.lower(),
                "width": width,
                "fields": fields,
            }
        )

    for item in regs:
        if len(out) >= limit:
            break
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        if "skipto" in item:
            offset = _int(item.get("skipto"), offset)
            continue
        if "reserved" in item:
            offset += _int(item.get("reserved"), 0) * stride
            continue
        if "window" in item:
            win = item["window"] if isinstance(item["window"], dict) else {}
            items = max(1, _int(win.get("items") or win.get("size"), 1))
            offset += items * stride
            continue
        if "multireg" in item:
            mr = item["multireg"] if isinstance(item["multireg"], dict) else {}
            base_name = str(mr.get("name") or "").strip()
            count = max(1, _int(mr.get("count"), 1))
            access = _SWACCESS.get(str(mr.get("swaccess") or "rw").lower(), "RW")
            fields = _fields_from(mr, access)
            reset = _reg_reset(mr, fields)
            width = _int(doc.get("regwidth"), 32)
            for n in range(count):
                if not base_name:
                    offset += stride
                    continue
                add(f"{base_name}{n}", offset, access, width, fields, reset)
                offset += stride
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            offset += stride
            continue
        access = _SWACCESS.get(str(item.get("swaccess") or "rw").lower(), "RW")
        fields = _fields_from(item, access)
        reset = _reg_reset(item, fields)
        width = _int(item.get("regwen_width") or doc.get("regwidth"), 32)
        add(name, offset, access, width, fields, reset)
        offset += stride
    return out


def memory_map_from_top_hjson(doc: Any) -> List[Dict[str, str]]:
    """Best-effort bases from a topgen-style file. Does not invent per-IP CSRs."""
    if not isinstance(doc, dict):
        return []
    out: List[Dict[str, str]] = []
    modules = doc.get("module") or doc.get("modules") or []
    if not isinstance(modules, list):
        return out
    for m in modules:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or m.get("type") or "").strip()
        bases = m.get("base_addrs") or m.get("base_addr")
        base = ""
        if isinstance(bases, dict) and bases:
            base = str(next(iter(bases.values())))
        elif isinstance(bases, str):
            base = bases
        elif m.get("base"):
            base = str(m.get("base"))
        if name and base:
            out.append({"name": name, "base": base, "size": str(m.get("size") or "")})
    return out


def csr_list_from_hjson_path(path: Union[str, Path], *, limit: int = 64) -> List[Dict[str, Any]]:
    return registers_from_ip_hjson(load_hjson(path), limit=limit)


def resolve_hjson_path(raw: Any) -> Optional[Path]:
    if not raw:
        return None
    p = Path(str(raw).strip().strip('"'))
    if p.is_file():
        return p
    return None
