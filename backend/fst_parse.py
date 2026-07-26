"""FST waveform ingestion via GTKWave's fst2vcd converter.

FST is GTKWave's binary waveform container. Pure-Python FST decoding is out of
scope, so ingestion is conversion based: FST -> VCD -> existing parse_vcd().
Never raises when the toolchain is absent; callers get ok=False plus a note.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

ENGINE = "gtkwave-fst2vcd"

INSTALL_NOTE = (
    "fst2vcd not found on PATH. Install GTKWave (ships fst2vcd/vcd2fst), or use the "
    "OSS CAD Suite bundle, or run the ChipSutra EDA Docker image. "
    "Ubuntu/Debian: apt-get install gtkwave. macOS: brew install --cask gtkwave."
)

# FST block ids (see GTKWave fstapi.c). A well formed file opens with a header
# block: one type byte followed by a big-endian uint64 section length.
_FST_BL_HDR = 0x00
_FST_BL_ZWRAPPER = 0xFE
_FST_HDR_SECTION_LEN = 329

_VCD_KEYWORDS = (
    "$date",
    "$version",
    "$timescale",
    "$comment",
    "$var",
    "$scope",
    "$upscope",
    "$enddefinitions",
    "$dumpvars",
)


def fst_tool() -> Optional[str]:
    """Absolute path to fst2vcd, or None when GTKWave is not installed."""
    return shutil.which("fst2vcd")


def vcd2fst_tool() -> Optional[str]:
    """Absolute path to vcd2fst (VCD -> FST direction), or None."""
    return shutil.which("vcd2fst")


def fst_available() -> bool:
    return fst_tool() is not None


def fst_status() -> Dict[str, object]:
    tool = fst_tool()
    return {
        "fst2vcd": tool is not None,
        "vcd2fst": vcd2fst_tool() is not None,
        "path": tool,
        "engine": ENGINE,
        "note": None if tool else INSTALL_NOTE,
    }


def sniff_waveform_format(data: bytes) -> str:
    """Classify raw waveform bytes as "fst", "vcd" or "unknown"."""
    if not data:
        return "unknown"
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, bytes):
        return "unknown"

    if len(data) >= 9:
        block = data[0]
        seclen = int.from_bytes(data[1:9], "big")
        if block == _FST_BL_HDR and seclen == _FST_HDR_SECTION_LEN:
            return "fst"
        if block == _FST_BL_ZWRAPPER and 0 < seclen < (1 << 48):
            return "fst"

    head = data[:8192]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    text = head.decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
    lowered = text.lower()
    for kw in _VCD_KEYWORDS:
        if lowered.startswith(kw):
            return "vcd"
    return "unknown"


def sniff_waveform_file(path: str | Path) -> str:
    """sniff_waveform_format() on the first bytes of a file; "unknown" if unreadable."""
    try:
        with open(path, "rb") as fh:
            return sniff_waveform_format(fh.read(8192))
    except Exception:
        return "unknown"


def convert_fst_to_vcd(fst_path: str | Path, out_vcd_path: str | Path, timeout: int = 120) -> Dict[str, object]:
    """Run `fst2vcd <fst> -o <vcd>`.

    Returns {"ok", "vcd_path", "stderr", "note"}. ok is False — never an
    exception — when the tool is missing, times out or exits non-zero.
    """
    tool = fst_tool()
    result: Dict[str, object] = {"ok": False, "vcd_path": None, "stderr": "", "note": None}
    if not tool:
        result["note"] = INSTALL_NOTE
        return result

    src = Path(fst_path)
    dst = Path(out_vcd_path)
    if not src.is_file():
        result["note"] = f"FST input not found: {src}"
        return result
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        result["note"] = f"Cannot create output directory {dst.parent}: {exc}"
        return result

    cmd = [tool, str(src), "-o", str(dst)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        result["note"] = f"fst2vcd timed out after {timeout}s on {src.name}"
        return result
    except Exception as exc:
        result["note"] = f"fst2vcd failed to launch: {exc}"
        return result

    result["stderr"] = (proc.stderr or "")[:4000]
    if proc.returncode != 0:
        result["note"] = f"fst2vcd exited with code {proc.returncode}"
        return result
    if not dst.is_file() or dst.stat().st_size == 0:
        result["note"] = "fst2vcd produced no VCD output"
        return result

    result["ok"] = True
    result["vcd_path"] = str(dst)
    return result


def ensure_vcd(path: str | Path, out_dir: Optional[str | Path] = None, timeout: int = 120) -> Dict[str, object]:
    """Return a VCD path for a waveform that may be FST or VCD.

    VCD inputs pass through untouched; FST inputs are converted next to the
    source (or into out_dir). Adds "format" and "converted" to the result dict.
    """
    src = Path(path)
    fmt = sniff_waveform_file(src)
    if fmt == "vcd":
        return {"ok": True, "vcd_path": str(src), "stderr": "", "note": None, "format": "vcd", "converted": False}
    if fmt == "unknown":
        return {
            "ok": False,
            "vcd_path": None,
            "stderr": "",
            "note": f"Unrecognized waveform format for {src.name} (expected VCD text or FST binary)",
            "format": "unknown",
            "converted": False,
        }
    base = Path(out_dir) if out_dir else src.parent
    out = base / (src.stem + ".vcd")
    res = convert_fst_to_vcd(src, out, timeout=timeout)
    res["format"] = "fst"
    res["converted"] = bool(res.get("ok"))
    return res
