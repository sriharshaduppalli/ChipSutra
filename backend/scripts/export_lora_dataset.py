"""Export (broken → repaired) / golden pairs for ChipSutra QLoRA fine-tuning (G8).

Sources:
  - eval_suite/chipsutra_out/*_raw.txt  (LLM first draft)
  - eval_suite/chipsutra_out/*_tb.sv    (post lint/repair)
  - knowledge/golden/*_tb.sv / *_class_sv_tb.sv
  - eval_suite/premium_refs/*_tb.sv

Writes JSONL ready for Unsloth / Axolotl / llama.cpp finetune:
  {"messages":[{"role":"system",...},{"role":"user",...},{"role":"assistant",...}]}

Usage:
  python scripts/export_lora_dataset.py
  python scripts/export_lora_dataset.py --out storage/lora/chipsutra_dv.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = Path(__file__).resolve().parent / "eval_suite"
GOLDEN = ROOT / "knowledge" / "golden"

SYSTEM = (
    "You are ChipSutra-VLSI. Output ONLY SystemVerilog for a Pure SV testbench "
    "(class-based unless the DUT is a bus protocol smoke). Declare every DUT port, "
    "independent golden, always #5 clk=~clk, $dumpfile/$dumpvars/$finish."
)


def _pair(user: str, assistant: str, tag: str) -> dict:
    return {
        "tag": tag,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": assistant.strip()},
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "storage" / "lora" / "chipsutra_dv.jsonl"),
    )
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []

    # 1) raw → repaired pairs from eval suite
    out_dir = SUITE / "chipsutra_out"
    duts = SUITE / "duts"
    if out_dir.is_dir():
        for tb_path in sorted(out_dir.glob("*_tb.sv")):
            name = tb_path.name.replace("_tb.sv", "")
            raw_path = out_dir / f"{name}_raw.txt"
            dut_path = duts / f"{name}.sv"
            if not dut_path.exists():
                continue
            repaired = tb_path.read_text(encoding="utf-8", errors="replace")
            rtl = dut_path.read_text(encoding="utf-8", errors="replace")
            user = f"Generate a Pure SV testbench (NO UVM) for this DUT:\n\n{rtl}"
            if raw_path.exists():
                raw = raw_path.read_text(encoding="utf-8", errors="replace")
                # Only keep pairs where repair changed something material
                if re.sub(r"\s+", "", raw) != re.sub(r"\s+", "", repaired):
                    rows.append(
                        _pair(
                            user + "\n\nRepair this draft into a correct TB:\n" + raw[:3500],
                            repaired[:6000],
                            f"repair:{name}",
                        )
                    )
            rows.append(_pair(user, repaired[:6000], f"final:{name}"))

    # 2) golden + premium refs as clean targets
    for folder, tag_prefix in ((GOLDEN, "golden"), (SUITE / "premium_refs", "premium")):
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*tb*.sv")):
            text = p.read_text(encoding="utf-8", errors="replace")
            # Try to find matching DUT by stem heuristics
            stem = p.stem.replace("_tb", "").replace("_smoke_sv", "").replace("_class_sv", "")
            dut = None
            for cand in (
                SUITE / "duts" / f"{stem}.sv",
                GOLDEN / f"{stem}.sv",
                GOLDEN / "axi_lite_slave.sv" if "axi" in stem else None,
            ):
                if cand and cand.exists():
                    dut = cand.read_text(encoding="utf-8", errors="replace")
                    break
            user = (
                f"Generate a Pure SV testbench matching this gold style for:\n\n{dut}"
                if dut
                else f"Generate the gold Pure SV testbench for design '{stem}'."
            )
            rows.append(_pair(user, text[:6000], f"{tag_prefix}:{p.name}"))

    # 2b) Ad-hoc repair pairs from storage/sim_* (e.g. mux_4to1 noop SB)
    sim_root = ROOT / "storage"
    if sim_root.is_dir():
        for broken in sorted(sim_root.glob("sim_*/**/*_broken_tb.sv")):
            fixed_path = broken.parent / broken.name.replace("_broken_tb.sv", "_tb.sv")
            dut_path = next(
                (
                    p
                    for p in [
                        SUITE / "duts" / (broken.parent.name.replace("sim_", "") + ".sv"),
                        broken.parent / (broken.parent.name.replace("sim_", "") + ".sv"),
                    ]
                    if p.exists()
                ),
                None,
            )
            if not fixed_path.exists() or not dut_path:
                continue
            raw = broken.read_text(encoding="utf-8", errors="replace")
            fixed = fixed_path.read_text(encoding="utf-8", errors="replace")
            rtl = dut_path.read_text(encoding="utf-8", errors="replace")
            tag = broken.parent.name.replace("sim_", "")
            user = f"Generate a Pure SV testbench (NO UVM) for this DUT:\n\n{rtl}"
            rows.append(
                _pair(
                    user + "\n\nRepair this draft into a correct TB:\n" + raw[:3500],
                    fixed[:6000],
                    f"repair:{tag}",
                )
            )
            rows.append(_pair(user, fixed[:6000], f"final:{tag}"))

    # 3) Fundamentals teaching pairs (must-know SV pillars + layered roles)
    for fund_name, tag_prefix in (
        ("sv_fundamentals_must_know.txt", "fundamentals"),
        ("layered_tb_components.txt", "layered"),
        ("sv_advanced_features_patterns.txt", "advanced"),
        ("sv_plusargs_patterns.txt", "plusargs"),
        ("sv_file_ops_patterns.txt", "fileops"),
        ("sv_tb_example_reg_ctrl.txt", "tb_example"),
        ("sv_tb_example_switch.txt", "tb_example"),
        ("sv_tb_example_adder.txt", "tb_example"),
        ("sv_functions_patterns.txt", "functions"),
        ("oss_eda_lab_flow.txt", "oss_lab"),
        ("sv_quick_refresher.txt", "refresher"),
        ("uvm_basics_intro.txt", "uvm_basics"),
        ("uvm_class_hierarchy.txt", "uvm_hierarchy"),
        ("uvm_installation.txt", "uvm_install"),
        ("uvm_hello.txt", "uvm_hello"),
        ("uvm_class_library.txt", "uvm_lib"),
        ("uvm_first_tb_dut.txt", "uvm_first_tb"),
        ("uvm_object.txt", "uvm_object"),
        ("uvm_transaction.txt", "uvm_txn"),
        ("uvm_component.txt", "uvm_comp"),
        ("uvm_driver.txt", "uvm_driver"),
        ("uvm_monitor.txt", "uvm_monitor"),
        ("uvm_subscriber.txt", "uvm_sub"),
        ("uvm_sequencer.txt", "uvm_sqr"),
        ("uvm_sequence.txt", "uvm_seq"),
        ("uvm_sequence_usage.txt", "uvm_seq_use"),
        ("uvm_scoreboard.txt", "uvm_sb"),
        ("uvm_agent.txt", "uvm_agent"),
        ("uvm_env.txt", "uvm_env"),
        ("uvm_test.txt", "uvm_test"),
        ("uvm_tb_top.txt", "uvm_top"),
        ("uvm_base_classes.txt", "uvm_base"),
        ("uvm_root.txt", "uvm_root"),
        ("uvm_object_pack.txt", "uvm_pack"),
        ("uvm_object_compare.txt", "uvm_compare"),
        ("uvm_object_print.txt", "uvm_print"),
        ("uvm_object_copy.txt", "uvm_copy"),
        ("uvm_utility_field_macros.txt", "uvm_utils"),
        ("uvm_field_macros.txt", "uvm_fields"),
        ("uvm_phases.txt", "uvm_phases"),
        ("uvm_objection.txt", "uvm_objection"),
        ("uvm_user_phases.txt", "uvm_user_phase"),
        ("uvm_factory_override.txt", "uvm_factory"),
        ("uvm_configure_components.txt", "uvm_configure"),
        ("uvm_resource_db.txt", "uvm_resource"),
        ("uvm_config_db.txt", "uvm_config_db"),
        ("uvm_config_db_examples.txt", "uvm_config_ex"),
        ("uvm_tlm.txt", "uvm_tlm"),
        ("uvm_tlm_blocking_put.txt", "uvm_tlm_put"),
        ("uvm_tlm_blocking_get.txt", "uvm_tlm_get"),
        ("uvm_tlm_fifo.txt", "uvm_tlm_fifo"),
        ("uvm_tlm_example.txt", "uvm_tlm_ex"),
        ("uvm_tlm_analysis.txt", "uvm_tlm_ap"),
        ("uvm_tlm_sockets.txt", "uvm_tlm_sock"),
        ("uvm_tlm_decl.txt", "uvm_tlm_decl"),
        ("uvm_tlm_nonblocking_put.txt", "uvm_tlm_nb_put"),
        ("uvm_tlm_port_export_imp.txt", "uvm_tlm_chain"),
        ("uvm_tlm_nonblocking_get.txt", "uvm_tlm_nb_get"),
        ("uvm_sequence_start.txt", "uvm_seq_start"),
        ("uvm_sequence_macros.txt", "uvm_seq_macros"),
        ("uvm_do.txt", "uvm_do"),
        ("uvm_send.txt", "uvm_send"),
        ("uvm_virtual_sequence.txt", "uvm_vseq"),
        ("uvm_virtual_sequencer.txt", "uvm_vseqr"),
        ("uvm_sequence_library.txt", "uvm_seq_lib"),
        ("uvm_sequence_arbitration.txt", "uvm_seq_arb"),
        ("uvm_reporting_classes.txt", "uvm_report"),
        ("uvm_reporting_functions.txt", "uvm_report_fn"),
        ("uvm_printer.txt", "uvm_printer"),
        ("uvm_comparer.txt", "uvm_comparer"),
        ("uvm_callback.txt", "uvm_callback"),
        ("uvm_event.txt", "uvm_event"),
        ("uvm_event_pool.txt", "uvm_event_pool"),
        ("uvm_ral.txt", "uvm_ral"),
        ("uvm_ral_classes.txt", "uvm_ral_cls"),
        ("uvm_ral_env.txt", "uvm_ral_env"),
        ("uvm_ral_connect.txt", "uvm_ral_conn"),
        ("uvm_ral_backdoor.txt", "uvm_ral_bd"),
        ("uvm_ral_example.txt", "uvm_ral_ex"),
        ("uvm_get_next_item.txt", "uvm_gni"),
        ("uvm_transaction_object.txt", "uvm_txn_obj"),
        ("uvm_get_put.txt", "uvm_get_put"),
        ("uvm_hdl_access.txt", "uvm_hdl"),
        ("uvm_singleton.txt", "uvm_singleton"),
        ("uvm_guide_reusable_vip.txt", "uvm_vip_guide"),
        ("uvm_guide_using_vip.txt", "uvm_uvc_guide"),
        ("uvm_tb_example_pattern.txt", "uvm_tb_pat"),
        ("uvm_tb_example1.txt", "uvm_tb_ex1"),
        ("uvm_tb_example2.txt", "uvm_tb_ex2"),
        ("uvm_patterns.txt", "uvm"),
        ("verification_methodologies_curriculum.txt", "methodology"),
        ("protocol_tb_guidance.txt", "proto_guide"),
        ("protocol_vip_axi_lite.txt", "vip_axil"),
        ("protocol_vip_apb.txt", "vip_apb"),
        ("protocol_vip_ahb.txt", "vip_ahb"),
        ("protocol_vip_axis.txt", "vip_axis"),
        ("protocol_vip_serial.txt", "vip_serial"),
        ("protocol_vip_simple.txt", "vip_simple"),
    ):
        fund = ROOT / "knowledge" / fund_name
        if not fund.exists():
            continue
        text = fund.read_text(encoding="utf-8", errors="replace")
        sections = re.split(r"(?m)^##\s+", text)
        for sec in sections[1:]:
            title, _, body = sec.partition("\n")
            body = body.strip()
            if len(body) < 40:
                continue
            rows.append(
                _pair(
                    f"Teach ChipSutra the SystemVerilog topic: {title.strip()}\n"
                    "Give the must-know rules for generating Pure SV testbenches.",
                    f"## {title.strip()}\n{body[:3500]}",
                    f"{tag_prefix}:{title.strip()[:40]}",
                )
            )

    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    meta = {
        "count": len(rows),
        "out": str(out),
        "tags": sorted({r["tag"].split(":")[0] for r in rows}),
    }
    (out.parent / "dataset_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
