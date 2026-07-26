"""Render a minimal cocotb + Verilator project scaffold."""
from __future__ import annotations

import re
from typing import Dict


def safe_ident(value: str, default: str = "dut") -> str:
    cleaned = re.sub(r"\W+", "_", value or "").strip("_")
    return cleaned or default


def render_cocotb_scaffold(top: str, rtl_filename: str) -> Dict[str, str]:
    top = safe_ident(top, "dut")
    rtl_filename = rtl_filename.replace("\\", "/").split("/")[-1]
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
    """Generated smoke test. Update reset/clock names to match the DUT."""
    if hasattr(dut, "clk"):
        cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
        await RisingEdge(dut.clk)
    dut._log.info("ChipSutra cocotb scaffold running for {top}")
''',
        "README.cocotb.md": f"""# cocotb scaffold for `{top}`

Install `cocotb` and Verilator, then run `make`.

The generated smoke test is intentionally conservative. Match clock/reset and
functional checks to `{rtl_filename}` before treating it as verification.
""",
    }
