"""Vendor-sim export for UVM source. ChipSutra Simulate does not run UVM."""
from __future__ import annotations

import io
import re
import zipfile
from typing import Dict, List, Optional, Sequence, Tuple

_UVM_RE = re.compile(
    r"\b(?:import\s+uvm_pkg|`include\s+\"uvm_macros|uvm_component|run_test\s*\()",
    re.I,
)
_TEST_RE = re.compile(
    r"run_test\s*\(\s*\"([A-Za-z_]\w*)\"\s*\)|"
    r"class\s+(\w+_test)\s+extends\s+uvm_test",
    re.I,
)


def looks_like_uvm(sv: str) -> bool:
    return bool(_UVM_RE.search(sv or ""))


def uvm_test_name(sv: str, fallback: str = "chipsutra_test") -> str:
    m = _TEST_RE.search(sv or "")
    if not m:
        return fallback
    return m.group(1) or m.group(2) or fallback


def _safe(name: str, idx: int = 0) -> str:
    n = re.sub(r"[^A-Za-z0-9_.\-]", "_", (name or "").split("/")[-1].split("\\")[-1])
    return n or f"src_{idx}.sv"


def render_filelist(rtl_names: Sequence[str], tb_name: str) -> str:
    lines = [
        "// ChipSutra UVM filelist — compile on Questa/VCS/Xcelium, not Verilator.",
        "+incdir+.",
        "+incdir+$UVM_HOME/src",
        "$UVM_HOME/src/uvm_pkg.sv",
    ]
    for n in rtl_names:
        if n and n != tb_name:
            lines.append(n)
    lines.append(tb_name)
    return "\n".join(lines) + "\n"


def render_readme(test: str, tb_name: str) -> str:
    return (
        "ChipSutra UVM export\n"
        "====================\n"
        "ChipSutra Simulate (Verilator) does not run UVM. This ZIP is source +\n"
        "drop-in scripts for a licensed simulator you already own.\n"
        "\n"
        f"TB: {tb_name}\n"
        f"Default +UVM_TESTNAME={test}\n"
        "\n"
        "Set UVM_HOME to Accellera uvm-1.2 (or your vendor UVM).\n"
        "Review the scoreboard before sign-off. ChipSutra is a copilot.\n"
    )


def render_questa(test: str, filelist: str = "filelist.f") -> str:
    return (
        f"# Questa / vsim — ChipSutra UVM export\n"
        f"vlib work\n"
        f"vlog -sv -f {filelist}\n"
        f"vsim -c work.chipsutra_opt -do \"run -all; quit\" "
        f"+UVM_TESTNAME={test} +UVM_NO_RELNOTES\n"
        f"# GUI: omit -c and -do, then `run -all`.\n"
    )


def render_vcs(test: str, filelist: str = "filelist.f") -> str:
    return (
        "#!/bin/sh\n"
        f"# Synopsys VCS — ChipSutra UVM export\n"
        f"vcs -full64 -sverilog -ntb_opts uvm-1.2 -f {filelist} -o simv \\\n"
        f"  +UVM_TESTNAME={test} +UVM_NO_RELNOTES\n"
        f"./simv +UVM_TESTNAME={test}\n"
    )


def render_xcelium(test: str, filelist: str = "filelist.f") -> str:
    return (
        "#!/bin/sh\n"
        f"# Cadence Xcelium — ChipSutra UVM export\n"
        f"xrun -sv -uvmhome CDNS-1.2 -f {filelist} \\\n"
        f"  +UVM_TESTNAME={test} +UVM_NO_RELNOTES\n"
    )


def build_vendor_files(
    sources: Sequence[Tuple[str, str]],
    *,
    tb_name: str = "tb.sv",
    tb_sv: str = "",
) -> Dict[str, str]:
    """sources: (filename, body). Last TB wins if tb_sv empty."""
    rtl_names: List[str] = []
    files: Dict[str, str] = {}
    detected_tb = tb_sv
    for i, (name, body) in enumerate(sources):
        safe = _safe(name, i)
        files[safe] = body or ""
        if looks_like_uvm(body or "") or safe == _safe(tb_name):
            detected_tb = body or detected_tb
            tb_name = safe
        else:
            rtl_names.append(safe)
    if tb_name not in files and detected_tb:
        files[_safe(tb_name)] = detected_tb
        tb_name = _safe(tb_name)
    test = uvm_test_name(detected_tb, "chipsutra_test")
    fl = render_filelist(rtl_names, tb_name)
    files["filelist.f"] = fl
    files["README_UVM.txt"] = render_readme(test, tb_name)
    files["run_questa.do"] = render_questa(test)
    files["run_vcs.sh"] = render_vcs(test)
    files["run_xcelium.sh"] = render_xcelium(test)
    files["UVM_TESTNAME.txt"] = test + "\n"
    return files


def vendor_pack_zip(files: Dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            if not name:
                continue
            zf.writestr(name.replace("\\", "/"), body or "")
    return buf.getvalue()


def uvm_refuse_message(test: str = "chipsutra_test") -> str:
    return (
        "UVM source detected. ChipSutra Simulate uses Verilator and cannot "
        f"run UVM. Download the vendor pack and run +UVM_TESTNAME={test} "
        "on Questa, VCS, or Xcelium. Or regenerate as Pure SV for local compile+run."
    )
