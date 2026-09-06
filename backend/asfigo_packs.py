"""Optional AsFigo extra packs (dirs on disk). Never vendors book/library SV.

ft_sva_BenCohen: catalog chapter/example *names* only — do not ingest .sv bodies.
ivl_uvm: IVL_UVM_HOME include path for Icarus.
MathLib: package include hint for sim-only real/vector math.
FPGALint/svck: CLI paths live in asfigo_bridge.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _dir(env_key: str, *alts: str) -> Optional[Path]:
    for key in (env_key, *alts):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir():
            return p
    return None


def ft_sva_catalog(root: Optional[Path] = None) -> Dict[str, Any]:
    """Index Fast-Track SVA example *filenames* only (no file bodies)."""
    base = root or _dir("CHIPSUTRA_FT_SVA_DIR")
    if not base:
        return {"available": False, "env": "CHIPSUTRA_FT_SVA_DIR"}
    fast = base / "fast_sva" if (base / "fast_sva").is_dir() else base
    chapters = sorted(p.name for p in fast.glob("ch*") if p.is_dir())
    examples: List[str] = []
    for ch in chapters:
        for f in sorted((fast / ch).glob("*.sv"))[:8]:
            examples.append(f"{ch}/{f.name}")
        if len(examples) >= 24:
            break
    return {
        "available": True,
        "env": "CHIPSUTRA_FT_SVA_DIR",
        "root": str(base),
        "chapters": chapters,
        "examples": examples,
        "note": "Local study catalog only — ChipSutra does not paste book listings into Generate.",
    }


def mathlib_status(root: Optional[Path] = None) -> Dict[str, Any]:
    base = root or _dir("CHIPSUTRA_MATHLIB_DIR")
    if not base:
        return {"available": False, "env": "CHIPSUTRA_MATHLIB_DIR"}
    src = base / "src" if (base / "src").is_dir() else base
    pkgs = sorted(p.name for p in src.glob("*pkg*.sv"))[:8]
    return {
        "available": True,
        "env": "CHIPSUTRA_MATHLIB_DIR",
        "root": str(base),
        "packages": pkgs or ["asfigo_MathLib_pkg.sv"],
        "note": "Sim-only real/vector helpers. Import the package; do not inline it. FPGA RTL must not use real.",
    }


def ivl_uvm_status(root: Optional[Path] = None) -> Dict[str, Any]:
    base = root or _dir("CHIPSUTRA_IVL_UVM", "IVL_UVM_HOME")
    if not base:
        return {"available": False, "env": "CHIPSUTRA_IVL_UVM"}
    inc = base / "ivl_uvm_src"
    return {
        "available": True,
        "env": "CHIPSUTRA_IVL_UVM",
        "root": str(base),
        "include": str(inc if inc.is_dir() else base),
        "note": "Icarus limited UVM (report/test). Not Accellera UVM. Not Verilator UVM sign-off.",
    }


def pack_status() -> Dict[str, Any]:
    return {
        "ft_sva": ft_sva_catalog(),
        "mathlib": mathlib_status(),
        "ivl_uvm": ivl_uvm_status(),
    }


def prompt_block(*, module: str = "") -> str:
    """Short Generate appendix when the user pointed extra packs at ChipSutra."""
    lines: List[str] = []
    ft = ft_sva_catalog()
    if ft.get("available") and module in ("", "assertions", "formal_hints", "debug"):
        ch = ", ".join(ft.get("chapters") or [])[:80]
        lines.append(
            f"User Fast-Track SVA catalog ({ft.get('root')}): chapters {ch}. "
            "Prefer labeled concurrent SVA with disable iff. Do not copy example file bodies."
        )
    ml = mathlib_status()
    if ml.get("available") and module in ("", "spec2rtl", "testbench", "checkers"):
        pkgs = ", ".join(ml.get("packages") or [])
        lines.append(
            f"User MathLib at {ml.get('root')} ({pkgs}). "
            "For sim-only real/matrix math, import that package; do not paste library source. "
            "Do not use real in FPGA/synth RTL."
        )
    ivl = ivl_uvm_status()
    if ivl.get("available") and module in ("", "testbench"):
        lines.append(
            f"User IVL_UVM at {ivl.get('root')}. Icarus UVM is messaging/test only — "
            "not Accellera UVM and not Verilator UVM sign-off. Prefer Pure SV for ChipSutra sim."
        )
    if not lines:
        return ""
    return "--- User AsFigo packs (local clone; do not vendor) ---\n" + "\n".join(lines)
