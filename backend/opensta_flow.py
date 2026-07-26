"""OpenSTA / SDC timing helpers: scaffold plus real runs when a liberty is supplied."""
from __future__ import annotations

import re
import shutil
from typing import Any, Dict, List, Optional


def sta_bin() -> Optional[str]:
    return shutil.which("sta") or shutil.which("opensta")


def _tcl_path(value: str) -> str:
    return value.replace("\\", "/")


def build_sta_tcl(
    *,
    netlist: str,
    liberty: Optional[str] = None,
    sdc: Optional[str] = None,
    top: Optional[str] = None,
    max_paths: int = 10,
) -> str:
    """Liberty must be read before the netlist for link_design to resolve cells."""
    lines: List[str] = []
    if liberty:
        lines.append(f'read_liberty "{_tcl_path(liberty)}"')
    else:
        lines.append("# No liberty (.lib) supplied — link_design will fail on a real run")
    lines.append(f'read_verilog "{_tcl_path(netlist)}"')
    if top:
        lines.append(f"link_design {top}")
    if sdc:
        lines.append(f'read_sdc "{_tcl_path(sdc)}"')
    else:
        lines.append("# No SDC provided — report_checks may be empty")
    lines.extend(
        [
            f"report_checks -path_delay max -max_paths {max_paths} "
            "-fields {slew cap input_pins nets fanout} -format full_clock_expanded",
            "report_checks -path_delay min -max_paths 5",
            "report_wns",
            "report_tns",
            "report_check_types -max_slew -max_capacitance -max_fanout -violators",
            "exit",
        ]
    )
    return "\n".join(lines) + "\n"


def sta_command(tcl_filename: str) -> List[str]:
    """OpenSTA runs a TCL script non-interactively with -exit."""
    binary = sta_bin()
    if not binary:
        raise RuntimeError("OpenSTA (`sta`) not found on PATH")
    return [binary, "-no_init", "-exit", tcl_filename]


def liberty_is_plausible(text: str) -> bool:
    """Cheap sanity check so we fail early instead of deep inside OpenSTA."""
    low = (text or "")[:20000].lower()
    return "library" in low and ("cell" in low or "wire_load" in low)


def parse_sta_log(log: str) -> Dict[str, Any]:
    wns = tns = None
    for line in (log or "").splitlines():
        m = re.search(r"\bwns\b[^-\d]*(-?\d+(?:\.\d+)?)", line, re.I)
        if m:
            try:
                wns = float(m.group(1))
            except Exception:
                pass
        m = re.search(r"\btns\b[^-\d]*(-?\d+(?:\.\d+)?)", line, re.I)
        if m:
            try:
                tns = float(m.group(1))
            except Exception:
                pass
        m = re.search(r"worst\s+slack\s*[:=]\s*(-?\d+(?:\.\d+)?)", line, re.I)
        if m and wns is None:
            try:
                wns = float(m.group(1))
            except Exception:
                pass
    errors = [ln.strip() for ln in (log or "").splitlines() if "error" in ln.lower()][:20]
    return {
        "wns": wns,
        "tns": tns,
        "violated": bool(wns is not None and wns < 0),
        "paths": parse_sta_paths(log),
        "errors": errors,
        "engine": "opensta",
    }


def parse_sta_paths(log: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Extract startpoint/endpoint/slack triples from report_checks output."""
    paths: List[Dict[str, Any]] = []
    start = end = None
    for line in (log or "").splitlines():
        m = re.search(r"Startpoint:\s*(\S+)", line)
        if m:
            start = m.group(1)
            end = None
            continue
        m = re.search(r"Endpoint:\s*(\S+)", line)
        if m:
            end = m.group(1)
            continue
        m = re.search(r"(-?\d+(?:\.\d+)?)\s+slack\s*\((MET|VIOLATED)\)", line, re.I)
        if m and (start or end):
            slack = float(m.group(1))
            paths.append(
                {
                    "startpoint": start,
                    "endpoint": end,
                    "slack": slack,
                    "status": m.group(2).upper(),
                }
            )
            start = end = None
            if len(paths) >= limit:
                break
    return paths


def default_sdc_stub(clock_name: str = "clk", period_ns: float = 10.0) -> str:
    return f"""# ChipSutra OpenSTA scaffold SDC
create_clock -name {clock_name} -period {period_ns} [get_ports {clock_name}]
set_input_delay -clock {clock_name} 0.1 [all_inputs]
set_output_delay -clock {clock_name} 0.1 [all_outputs]
"""
