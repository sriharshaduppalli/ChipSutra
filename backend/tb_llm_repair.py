"""Optional second-pass LLM repair when class-SV competitive score is low."""
from __future__ import annotations

import os
from typing import List, Optional, Tuple


REPAIR_SYSTEM = """You are ChipSutra-VLSI repairing a Pure SV testbench (NO UVM).
Fix ONLY the listed lint/compiler issues. Prefer keeping the existing structure
(txn+scoreboard smoke OR full IF/gen/drv/mon/sb/env/test).
Rules: legal SV only (task→endtask, function→endfunction; NO C-style {{ }} bodies);
declare scoreboard members before use (`logic […] expected;`); module owns `errors`
(never sb.errors++ unless SB declares errors); empty constraints illegal — use inside {[0:1]};
FIFO: clamp wr/rd vs sb.q.size() after randomize; FWFT check after predict;
combo DUT: never map invented .clk/.rst_n onto DUT; skip reset if DUT has no reset;
NEVER ship `function bit check(); return 1;` — for mux use ternary/case(sel) golden;
independent golden; $dumpfile/$dumpvars/$finish; ONE PASS/FAIL at end.
Output ONLY SystemVerilog. No markdown."""


def should_llm_repair(
    *,
    issues: List[str],
    competitive_score: Optional[int] = None,
    premium_bar: bool = False,
) -> bool:
    """Second LLM pass only when mechanical repair left real gaps (saves latency)."""
    if os.environ.get("CHIPSUTRA_LLM_REPAIR", "true").lower() in ("0", "false", "no"):
        return False
    if premium_bar:
        return False

    iss = list(issues or [])
    # Mechanical usually clears these; if they remain, try LLM once.
    still_needs_model = any(
        i
        in {
            "no_module",
            "circular_golden",
            "missing_dut_instance",
            "missing_posedge_sync",
            "task_with_return",
            "noop_constraint",
            "undeclared_errors",
            "undeclared_expected",
            "incomplete_module",
            "semantic_fifo_reset_rd_data",
            "sb_errors_not_member",
            "missing_new_construct",
            # Semantic golden bugs need model reasoning, not regex repair.
            "semantic_circular_out",
            "semantic_fifo_no_queue",
            "semantic_fifo_count_arith",
            "semantic_fifo_no_clamp",
            "semantic_axi_no_ready_wait",
            "semantic_axi_no_resp_check",
            "semantic_axi_no_timeout",
            "semantic_axi_no_wstrb",
            "semantic_apb_no_access_phase",
            "semantic_apb_no_pready_wait",
            "semantic_apb_no_timeout",
            "semantic_apb_no_model_reg",
            "semantic_noop_check",
            "semantic_mux_no_select",
            "semantic_missing_post_reset_check",
            "semantic_stuck_active_low_reset",
            "stuck_active_low_reset",
            "missing_sv_interface",
            "missing_sv_generator",
            "missing_sv_driver",
            "missing_sv_monitor",
            "missing_sv_env",
            "missing_sv_test",
            "layered_syntax_broken",
            "semantic_stream_no_ready_wait",
            "semantic_ahb_no_htrans",
        }
        or i.startswith("undeclared_signal:")
        or i.startswith("drives_dut_output:")
        or i.startswith("missing_port_map:")
        for i in iss
    )
    if still_needs_model:
        return True
    # Low bar only — avoid expensive 2nd pass for soft nits (score 75–89).
    if competitive_score is not None and competitive_score < 70:
        return True
    return False


def build_repair_user_prompt(
    broken_sv: str,
    issues: List[str],
    *,
    dut_hint: str = "",
    compiler_errors: Optional[List[str]] = None,
) -> str:
    iss = ", ".join(issues[:12]) or "quality gaps"
    hint = f"\nDUT context: {dut_hint}\n" if dut_hint else "\n"
    comp = ""
    if compiler_errors:
        lines = "\n".join(f"  {e}" for e in compiler_errors[:10])
        comp = (
            "\nVerilator COMPILER ERRORS (fix every one; file:line points at the TB):\n"
            f"{lines}\n"
        )
    return (
        f"Repair this class-based Pure SV TB. Lint issues: {iss}.{hint}{comp}\n"
        "Broken code:\n"
        f"{broken_sv.strip()}\n"
    )


async def llm_repair_class_sv(
    *,
    provider: str,
    model: str,
    broken_sv: str,
    issues: List[str],
    dut_hint: str = "",
    session_id: str = "",
    compiler_errors: Optional[List[str]] = None,
) -> Tuple[str, bool]:
    """Run one repair generate. Returns (text, ok_streamed)."""
    from llm_provider import stream_chat

    chunks: List[str] = []
    user = build_repair_user_prompt(
        broken_sv, issues, dut_hint=dut_hint, compiler_errors=compiler_errors
    )
    try:
        async for delta in stream_chat(
            provider=provider,
            model=model,
            system=REPAIR_SYSTEM,
            user_text=user,
            session_id=session_id or None,
            num_predict=int(os.environ.get("OLLAMA_NUM_PREDICT_REPAIR", "2000")),
        ):
            chunks.append(delta)
    except Exception:
        return broken_sv, False
    text = "".join(chunks).strip()
    # Truncated output (no endmodule) is worse than the input — reject it
    if text and "endmodule" not in text:
        return broken_sv, False
    return (text if text else broken_sv), bool(text)
