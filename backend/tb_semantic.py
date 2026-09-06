"""Protocol-aware semantic checks for TB goldens (counter / fifo / parity)."""
from __future__ import annotations

import re
from typing import List

# expected/exp derived from DUT count output (circular). RHS lookahead excludes
# self-increment goldens like `expected_count = expected_count + 1` (correct model).
_CIRCULAR_COUNT = re.compile(
    r"\b(?:exp|expected|exp_count|golden)\w*\s*<?=\s*"
    r"(?!(?:exp|expected|golden))\w*(?:count|q|data_out|rd_data)\w*\s*\+\s*",
    re.I,
)
_EXPECTED_RD_DATA = re.compile(r"\bexpected\s*=\s*rd_data\b", re.I)
_EXPECTED_FULL = re.compile(r"\bexpected\s*=\s*full\b", re.I)
_HAS_QUEUE = re.compile(
    r"\bq\s*\[\s*\$\s*\]|\b(?:logic|reg|bit)\b[^;\n]*\[\s*\$\s*\]",
    re.I,
)
_HAS_WR_RD = re.compile(r"\bwr_en\b.*\brd_en\b|\brd_en\b.*\bwr_en\b", re.I | re.S)
_HAS_XOR = re.compile(r"\^|\bxor\b", re.I)
_MENTIONS_PARITY = re.compile(r"\bparity\b", re.I)
_PREDICT_FN = re.compile(
    r"function\s+(?:void\s+|automatic\s+)*\w*\s*predict\s*\(([^)]*)\)",
    re.I,
)
_SCOREBOARD_CLASS = re.compile(
    r"\bclass\s+\w*scoreboard\w*\b[\s\S]*?\bendclass\b",
    re.I,
)


def lint_semantic_golden(sv: str, protocol: str = "generic") -> List[str]:
    """Return semantic issue strings (empty if OK)."""
    if not sv:
        return []
    issues: List[str] = []
    proto = (protocol or "generic").lower()

    # Circular: expected from DUT outs (count+/rd_data/full)
    if _CIRCULAR_COUNT.search(sv) or _EXPECTED_RD_DATA.search(sv) or _EXPECTED_FULL.search(sv):
        issues.append("semantic_circular_out")

    if proto == "counter" or (
        proto == "generic" and re.search(r"\bclass\s+\w*scoreboard\w*", sv, re.I)
        and re.search(r"\bcount\b", sv, re.I)
    ):
        if proto == "counter":
            for block in _SCOREBOARD_CLASS.findall(sv):
                for m in _PREDICT_FN.finditer(block):
                    params = m.group(1).lower()
                    if not re.search(r"\b(en|enable)\b", params):
                        issues.append("semantic_counter_predict_no_enable")
                        break

    # FIFO: need queue model when wr_en/rd_en present
    if proto == "fifo" or (proto == "generic" and _HAS_WR_RD.search(sv)):
        if (proto == "fifo" or _HAS_WR_RD.search(sv)) and not _HAS_QUEUE.search(sv):
            if re.search(r"\bwr_en\b", sv, re.I) and re.search(r"\brd_en\b", sv, re.I):
                issues.append("semantic_fifo_no_queue")
        # Queue exists but occupancy tracked by separate +/- arithmetic — a
        # classic runtime-FAIL source; the golden count should be q.size().
        if _HAS_QUEUE.search(sv) and re.search(
            r"\bexpected\w*count\w*\s*=\s*expected\w*count\w*\s*[-+]", sv, re.I
        ):
            issues.append("semantic_fifo_count_arith")
        # Random wr/rd without occupancy clamps → push-on-full / pop-on-empty sim fails
        if _HAS_QUEUE.search(sv) and re.search(r"txn\.randomize\s*\(", sv, re.I):
            has_wr_clamp = bool(
                re.search(
                    r"q\.size\s*\(\s*\)\s*>=\s*[^;]{0,40}?wr_en\s*=\s*(?:1'b0|0)",
                    sv,
                    re.I | re.S,
                )
            )
            has_rd_clamp = bool(
                re.search(
                    r"q\.size\s*\(\s*\)\s*==\s*0[\s\S]{0,60}?rd_en\s*=\s*(?:1'b0|0)",
                    sv,
                    re.I,
                )
            )
            if not (has_wr_clamp and has_rd_clamp):
                issues.append("semantic_fifo_no_clamp")
        # FWFT mem is often X after reset — requiring rd_data==='0 fails a good DUT
        if re.search(
            r"(?:rst_n|aresetn)\s*=\s*(?:1'b1|1)\s*;[\s\S]{0,500}?"
            r"\brd_data\s*!==\s*(?:'0|1'b0|\d+'h0+|0)\b",
            sv,
            re.I,
        ):
            issues.append("semantic_fifo_reset_rd_data")

    # AXI-Lite: handshake discipline in the TB stimulus/golden
    is_axi = proto in ("axi", "axi_lite", "axi4_lite") or bool(
        re.search(r"\bawvalid\b|\bs_axi_awvalid\b", sv, re.I)
    )
    if is_axi and re.search(r"awvalid\s*<?=\s*1", sv, re.I):
        # Drives AWVALID but never observes AWREADY → protocol violation
        if not re.search(r"\bawready\b|\bs_axi_awready\b", sv, re.I):
            issues.append("semantic_axi_no_ready_wait")
        # Never checks a response code (BRESP/RRESP)
        if not re.search(r"\bbresp\b|\brresp\b|s_axi_[br]resp", sv, re.I):
            issues.append("semantic_axi_no_resp_check")
        # Unbounded handshake waits hang simulations — require a timeout guard
        if re.search(
            r"(?:wait\s*\(|while\s*\(\s*!)[^;\n]*(?:ready|valid)", sv, re.I
        ) and not re.search(r"\btimeout\b|\bwatchdog\b", sv, re.I):
            issues.append("semantic_axi_no_timeout")
        # Writes without WSTRB=all-ones silently mask every byte on many slaves
        if re.search(r"wvalid\s*<?=\s*1", sv, re.I) and not re.search(
            r"wstrb\s*<?=\s*(?:4'h[fF]|4'b1111|'1)", sv, re.I
        ):
            issues.append("semantic_axi_no_wstrb")

    # APB: SETUP (PSEL&&!PENABLE) then ACCESS (PSEL&&PENABLE); wait PREADY
    is_apb = proto == "apb" or bool(
        re.search(r"\bpsel\b|\bPSEL\b", sv) and re.search(r"\bpenable\b|\bPENABLE\b", sv)
    )
    if is_apb and re.search(r"\bpsel\s*<?=\s*1|\bPSEL\s*<?=\s*1", sv, re.I):
        if not re.search(r"\bpenable\s*<?=\s*1|\bPENABLE\s*<?=\s*1", sv, re.I):
            issues.append("semantic_apb_no_access_phase")
        if not re.search(r"\bpready\b|\bPREADY\b", sv):
            issues.append("semantic_apb_no_pready_wait")
        if re.search(
            r"(?:wait\s*\(|while\s*\(\s*!)[^;\n]*pready", sv, re.I
        ) and not re.search(r"\btimeout\b|\bwatchdog\b", sv, re.I):
            issues.append("semantic_apb_no_timeout")
        if not re.search(
            r"\bmodel_reg\b|\bregs\s*\[|_reg_model\b|\bpredict_write\b|\buvm_reg\b",
            sv,
            re.I,
        ):
            issues.append("semantic_apb_no_model_reg")

    # AXI-Stream / valid-ready stream
    is_stream = proto in ("stream", "axis", "axi_stream") or bool(
        re.search(r"\btvalid\b|\bs_axis_tvalid\b", sv, re.I)
    )
    if is_stream and re.search(r"tvalid\s*<?=\s*1|valid\s*<?=\s*1", sv, re.I):
        if not re.search(r"\btready\b|\bready\b", sv, re.I):
            issues.append("semantic_stream_no_ready_wait")

    # AHB-Lite
    is_ahb = proto == "ahb" or bool(re.search(r"\bhtrans\b|\bHTRANS\b", sv))
    if is_ahb and re.search(r"\bhsel\s*<?=\s*1|\bHSEL\s*<?=\s*1", sv, re.I):
        if not re.search(r"\bhtrans\b|\bHTRANS\b", sv):
            issues.append("semantic_ahb_no_htrans")
        if not re.search(r"\bhready\b|\bHREADY", sv):
            issues.append("semantic_ahb_no_hready")

    # SPI: need cs_n/sclk/mosi drive
    if proto == "spi" or re.search(r"\bmosi\b", sv, re.I):
        if re.search(r"\bmosi\b", sv, re.I) and not re.search(r"\bcs_n\b|\bcss\b", sv, re.I):
            issues.append("semantic_spi_no_cs")

    # UART TX: start pulse + wait busy/done
    if proto == "uart" or (re.search(r"\btx\b", sv, re.I) and re.search(r"\bstart\b", sv, re.I)):
        if re.search(r"\bstart\s*<?=\s*1", sv, re.I) and not re.search(
            r"\bbusy\b|\bdone\b", sv, re.I
        ):
            issues.append("semantic_uart_no_done_wait")

    # Parity: prefer ^ / xor in check/predict
    if proto == "parity" or (proto == "generic" and _MENTIONS_PARITY.search(sv)):
        if _MENTIONS_PARITY.search(sv) and not _HAS_XOR.search(sv):
            # Only flag when there is a check/predict path
            if re.search(r"\b(?:check|predict|expected)\b", sv, re.I):
                issues.append("semantic_parity_no_xor")

    # Noop scoreboard: `function bit check(); return 1;` never verifies DUT
    if re.search(
        r"function\s+bit\s+check\s*\(\s*\)\s*;\s*return\s+1\s*;",
        sv,
        re.I,
    ):
        issues.append("semantic_noop_check")

    # Mux: sel + data inputs but scoreboard never selects on sel
    looks_mux = bool(
        re.search(r"\bsel\b", sv, re.I)
        and re.search(r"\b(?:d0|in0|\ba\b)\b", sv, re.I)
        and re.search(r"\b(?:y|out|dout)\b", sv, re.I)
        and re.search(r"\bclass\s+\w*scoreboard\w*", sv, re.I)
    )
    if proto == "mux" or looks_mux:
        sb_blocks = _SCOREBOARD_CLASS.findall(sv)
        has_select_golden = any(
            re.search(
                r"case\s*\(\s*\w*sel|sel\s*\?\s*\w+\s*:\s*\w+|expected\s*=\s*\w*d\d|"
                r"\?\s*\w+\s*:\s*\w+|if\s*\([^;]{0,40}\)\s*expected\s*=|"
                r"expected\s*=\s*\([^)]*\?\s*\w+\s*:\s*\w+",
                blk,
                re.I,
            )
            for blk in sb_blocks
        )
        if sb_blocks and not has_select_golden:
            issues.append("semantic_mux_no_select")

    # Stuck active-low reset: last rst_n assign before for-loop holds reset
    m_init = re.search(r"initial\s+begin([\s\S]*?)\n\s*for\s*\(", sv, re.I)
    if m_init:
        assigns = list(
            re.finditer(r"\brst_n\s*=\s*(1'b[01]|[01])\s*;", m_init.group(1), re.I)
        )
        if assigns and assigns[-1].group(1).lower() in ("0", "1'b0"):
            issues.append("semantic_stuck_active_low_reset")

    # Post-reset output-value check (kills drop_reset mutants)
    # Accept inline TB or layered test after drv.reset() / rst deassert.
    has_release = re.search(
        r"(?:rst_n|aresetn|PRESETn|HRESETn)\s*=\s*(?:1'b0|0)\s*;[\s\S]{0,400}?"
        r"(?:rst_n|aresetn|PRESETn|HRESETn)\s*=\s*(?:1'b1|1)\s*;",
        sv,
        re.I,
    )
    has_post_reset_check = bool(
        re.search(
            r"(?:\.reset\s*\(|(?:rst_n|aresetn|PRESETn|HRESETn)\s*=\s*(?:1'b1|1))"
            r"[\s\S]{0,800}?(?:!==\s*'0|!==\s*1'b0)[\s\S]{0,160}?errors",
            sv,
            re.I,
        )
    )
    if has_release:
        if not has_post_reset_check and re.search(
            r"\b(?:count|parity|empty|full|prdata|hrdata|rdata)\b", sv, re.I
        ):
            issues.append("semantic_missing_post_reset_check")
    elif re.search(r"\brst_n\b|\baresetn\b", sv, re.I) and re.search(
        r"\b(?:count|parity)\b", sv, re.I
    ):
        if "semantic_stuck_active_low_reset" not in issues and not has_post_reset_check:
            issues.append("semantic_missing_post_reset_check")

    return list(dict.fromkeys(issues))
