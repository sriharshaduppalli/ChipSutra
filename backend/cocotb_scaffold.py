"""Render a minimal cocotb + Verilator project scaffold."""
from __future__ import annotations

import re
from typing import Dict, Optional


def safe_ident(value: str, default: str = "dut") -> str:
    cleaned = re.sub(r"\W+", "_", value or "").strip("_")
    return cleaned or default


def _clock_reset_from_rtl(rtl_text: str) -> tuple[Optional[str], Optional[str], bool]:
    if not (rtl_text or "").strip():
        return None, None, True
    try:
        from rtl_ports import extract_modules
        from tb_skeleton import classify_ports

        mods = extract_modules(rtl_text)
        if not mods:
            return None, None, True
        cls = classify_ports(list(mods[0].get("ports") or []))
        clk = (cls.get("clk") or {}).get("name")
        rst = (cls.get("rst") or {}).get("name")
        active_low = bool(cls.get("active_low_reset", True))
        return clk, rst, active_low
    except Exception:
        return None, None, True


def render_cocotb_scaffold(
    top: str,
    rtl_filename: str,
    *,
    rtl_text: str = "",
    clk_name: Optional[str] = None,
    rst_name: Optional[str] = None,
    active_low: bool = True,
) -> Dict[str, str]:
    top = safe_ident(top, "dut")
    rtl_filename = rtl_filename.replace("\\", "/").split("/")[-1]
    parsed_clk, parsed_rst, parsed_low = _clock_reset_from_rtl(rtl_text)
    clk = clk_name or parsed_clk or "clk"
    rst = rst_name or parsed_rst
    if rst_name is None and parsed_rst:
        active_low = parsed_low
    rst_assert = "0" if active_low else "1"
    rst_deassert = "1" if active_low else "0"
    rst_block = ""
    if rst:
        rst_block = f"""
    if hasattr(dut, "{rst}"):
        dut.{rst}.value = {rst_assert}
        await RisingEdge(dut.{clk})
        dut.{rst}.value = {rst_deassert}
        await RisingEdge(dut.{clk})
"""
    return {
        "Makefile": f"""SIM ?= verilator
TOPLEVEL_LANG ?= verilog
VERILOG_SOURCES += $(PWD)/{rtl_filename}
TOPLEVEL = {top}
MODULE = test_{top}

include $(shell cocotb-config --makefiles)/Makefile.sim
""",
        f"test_{top}.py": f'''import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


@cocotb.test()
async def smoke_{top}(dut):
    """Generated smoke test. Clock/reset names taken from parsed DUT ports when available."""
    if hasattr(dut, "{clk}"):
        cocotb.start_soon(Clock(dut.{clk}, 10, unit="ns").start())
        await RisingEdge(dut.{clk})
{rst_block}    dut._log.info("ChipSutra cocotb scaffold running for {top}")
''',
        "README.cocotb.md": f"""# cocotb scaffold for `{top}`

Install `cocotb` and Verilator, then run `make`.

Clock `{clk}`"""
        + (f" and reset `{rst}`" if rst else "")
        + f""" were inferred from `{rtl_filename}` when possible.
Match remaining functional checks to the DUT before treating this as verification.
""",
    }
