"""Semantic golden lint — counter / fifo / parity."""
from tb_semantic import lint_semantic_golden


def test_counter_circular_and_predict_enable():
    bad = """
    class counter_scoreboard;
      logic [3:0] expected;
      function void predict();
        expected = count + 1;
      endfunction
    endclass
    """
    issues = lint_semantic_golden(bad, protocol="counter")
    assert "semantic_circular_out" in issues
    assert "semantic_counter_predict_no_enable" in issues


def test_counter_self_increment_golden_is_not_circular():
    """`expected_count = expected_count + 1` is an INDEPENDENT golden, not circular."""
    good = """
    class counter_scoreboard;
      logic [3:0] expected_count;
      function void predict(bit enable);
        if (enable) expected_count = expected_count + 4'd1;
      endfunction
      function bit check(logic [3:0] actual);
        return (actual === expected_count);
      endfunction
    endclass
    """
    issues = lint_semantic_golden(good, protocol="counter")
    assert "semantic_circular_out" not in issues


def test_fifo_needs_queue():
    bad = """
    module fifo_tb;
      logic wr_en, rd_en;
      logic [7:0] rd_data, expected;
      initial begin
        expected = rd_data;
      end
    endmodule
    """
    issues = lint_semantic_golden(bad, protocol="fifo")
    assert "semantic_fifo_no_queue" in issues
    assert "semantic_circular_out" in issues


def test_noop_check_and_mux_select():
    bad = """
    class mux_scoreboard;
      function void predict(); beats++; endfunction
      function bit check(); return 1; endfunction
    endclass
    module mux_tb;
      logic [1:0] sel; logic d0, d1, y;
    endmodule
    """
    issues = lint_semantic_golden(bad, protocol="generic")
    assert "semantic_noop_check" in issues
    assert "semantic_mux_no_select" in issues


def test_axi_semantics():
    bad = """
    module axi_tb;
      logic aclk, aresetn, s_axi_awvalid, s_axi_wvalid;
      initial begin
        s_axi_awvalid = 1'b1;
        s_axi_wvalid = 1'b1;
        while (!done_valid) @(posedge aclk);
      end
    endmodule
    """
    issues = lint_semantic_golden(bad, protocol="axi_lite")
    assert "semantic_axi_no_ready_wait" in issues
    assert "semantic_axi_no_resp_check" in issues
    assert "semantic_axi_no_timeout" in issues
    assert "semantic_axi_no_wstrb" in issues


def test_apb_semantics():
    bad = """
    module apb_tb;
      logic PSEL, PENABLE;
      initial begin
        PSEL = 1'b1;
        // missing access phase, ready wait, and register model
      end
    endmodule
    """
    issues = lint_semantic_golden(bad, protocol="apb")
    assert "semantic_apb_no_access_phase" in issues
    assert "semantic_apb_no_pready_wait" in issues
    assert "semantic_apb_no_model_reg" in issues


def test_apb_ral_named_model_is_accepted():
    ok_sv = """
    class apb_regs_reg_model;
      logic [31:0] CTRL;
      function void predict_write(logic [31:0] addr, logic [31:0] data);
        CTRL = data;
      endfunction
    endclass
    module apb_tb;
      logic PSEL, PENABLE, PREADY;
      initial begin
        PSEL = 1'b1; PENABLE = 1'b1;
        while (!PREADY && timeout < 40) @(posedge PCLK);
      end
    endmodule
    """
    issues = lint_semantic_golden(ok_sv, protocol="apb")
    assert "semantic_apb_no_model_reg" not in issues


def test_axi_golden_ref_is_clean():
    from pathlib import Path

    gold = (
        Path(__file__).resolve().parents[1]
        / "knowledge" / "golden" / "axi_lite_smoke_sv_tb.sv"
    ).read_text(encoding="utf-8")
    issues = lint_semantic_golden(gold, protocol="axi_lite")
    assert not [i for i in issues if i.startswith("semantic_axi_")], issues


def test_parity_wants_xor():
    bad = """
    class parity_scoreboard;
      function bit check(logic parity);
        return (parity === expected);
      endfunction
    endclass
    """
    issues = lint_semantic_golden(bad, protocol="parity")
    assert "semantic_parity_no_xor" in issues
    good = "function void predict; if (valid) expected = ^data; endfunction"
    assert lint_semantic_golden(good, protocol="parity") == []


def test_fifo_no_clamp_flagged():
    bad = """
    class fifo_scoreboard;
      logic [7:0] q[$];
    endclass
    module fifo_tb;
      logic wr_en, rd_en;
      initial begin
        assert(txn.randomize());
        wr_en = txn.wr_en;
      end
    endmodule
    """
    issues = lint_semantic_golden(bad, protocol="fifo")
    assert "semantic_fifo_no_clamp" in issues
    good = bad.replace(
        "assert(txn.randomize());",
        "assert(txn.randomize()); if (sb.q.size() >= 8) txn.wr_en = 0; if (sb.q.size() == 0) txn.rd_en = 0;",
    )
    assert "semantic_fifo_no_clamp" not in lint_semantic_golden(good, protocol="fifo")


def test_fifo_reset_rd_data_flagged():
    sv = """
    module fifo_tb;
      logic [7:0] q[$];
      logic wr_en, rd_en, rd_data, rst_n, clk;
      initial begin
        rst_n = 0; @(posedge clk); rst_n = 1; @(posedge clk);
        if (rd_data !== '0 || empty !== 1) errors++;
      end
    endmodule
    """
    issues = lint_semantic_golden(sv, protocol="fifo")
    assert "semantic_fifo_reset_rd_data" in issues

