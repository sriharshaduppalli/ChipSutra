"""Smoke: generate a Verilator-friendly TB for counter_rtl via local Ollama."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generation_rules import rules_for_module, default_user_prompt, num_predict_for_module
from rtl_ports import extract_port_context_from_texts
from llm_provider import stream_chat

COUNTER = Path(r"C:\Users\sriha\Desktop\ChipSutra_EDA\counter_rtl.v").read_text(encoding="utf-8")


async def main() -> int:
    port_block = extract_port_context_from_texts([COUNTER])
    system = (
        "You are an expert VLSI verification engineer. Generate a Verilator-friendly "
        "SystemVerilog testbench (pure SV by default). Never invent ports. Output ONLY SystemVerilog.\n\n"
        + "--- Parsed RTL interfaces ---\n"
        + port_block
        + "\n\n"
        + rules_for_module("testbench", has_ports=True)
    )
    user = default_user_prompt("testbench", dut_hint="module counter_rtl")
    user += f"\n\n--- FILE: counter_rtl.v ---\n{COUNTER}\n"

    chunks: list[str] = []
    predict = num_predict_for_module("testbench")
    async for delta in stream_chat(
        "ollama",
        "chipsutra-vlsi:3b",
        system,
        user,
        session_id="smoke-tb",
        num_predict=predict,
    ):
        chunks.append(delta)
        print(delta, end="", flush=True)
    print("\n====CHECKS====")
    out = "".join(chunks)
    directed_cases = len(re.findall(r"(?i)test\s*case\s*\d+", out))
    checks = {
        "has_counter_rtl_inst": bool(re.search(r"counter_rtl\s+\w+", out)),
        "has_enable": "enable" in out,
        "has_count": "count" in out,
        "has_urandom": bool(re.search(r"\$urandom(_range)?", out)),
        "few_directed_cases": directed_cases <= 3,
        "directed_case_count": directed_cases,
        "line_count": out.count("\n") + 1,
        "no_data_in": "data_in" not in out,
        "no_certainly": "Certainly" not in out,
        "no_fake_put": ".put()" not in out,
        "has_dumpvars": "$dumpvars" in out or "$dumpfile" in out,
        "has_finish": "$finish" in out,
        "num_predict": predict,
    }
    print(json.dumps(checks, indent=2))
    ok = all(
        [
            checks["has_counter_rtl_inst"],
            checks["has_enable"],
            checks["has_count"],
            checks["no_data_in"],
            checks["no_certainly"],
            checks["no_fake_put"],
            checks["has_urandom"] or checks["few_directed_cases"],
        ]
    )
    print("SMOKE_OK" if ok else "SMOKE_WEAK")
    return 0 if ok else 1


if __name__ == "__main__":
    # Ensure OLLAMA_URL for llm_provider
    import os

    os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")
    os.environ.setdefault("OLLAMA_MODEL", "chipsutra-vlsi:3b")
    raise SystemExit(asyncio.run(main()))
