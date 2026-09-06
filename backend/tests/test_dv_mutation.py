"""Mutation operators prefer functionally visible faults."""
from dv_mutation import (
    _mut_and_to_or,
    generate_mutants,
    mutation_test,
    mutation_worker_count,
)


def test_and_to_or_prefers_access_not_setup():
    rtl = """
module apb_regs;
  wire setup  = PSEL && !PENABLE;
  wire access = PSEL && PENABLE;
  always @(posedge PCLK) begin
    if (access) regs[PADDR[3:2]] <= PWDATA;
  end
endmodule
"""
    out = _mut_and_to_or(rtl)
    assert out is not None
    assert "access = PSEL || PENABLE" in out or "access = PSEL|| PENABLE" in out.replace(" ", "")
    assert "setup  = PSEL && !PENABLE" in out


def test_and_to_or_prefers_wr_hs():
    rtl = """
module axi;
  wire wr_start = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
  wire wr_hs    = s_axi_awready && s_axi_awvalid && s_axi_wready && s_axi_wvalid;
endmodule
"""
    out = _mut_and_to_or(rtl)
    assert out is not None
    wr_hs_rhs = out.split("wr_hs")[1].split(";")[0]
    assert "||" in wr_hs_rhs
    assert wr_hs_rhs.rstrip().endswith("s_axi_wvalid") or "wvalid" in wr_hs_rhs


def test_generate_mutants_applies():
    rtl = "module t; wire a = b && c; always @(posedge clk) if (!rst_n) q<=0; else q<=q+1'b1; endmodule"
    names = {n for n, _ in generate_mutants(rtl)}
    assert "and_to_or" in names
    assert "drop_reset" in names
    assert "off_by_one" in names


def test_mutation_worker_count_caps():
    assert mutation_worker_count(0) == 1
    assert mutation_worker_count(1) == 1
    assert mutation_worker_count(6, requested=1) == 1
    assert mutation_worker_count(6, requested=8) == 4
    assert mutation_worker_count(3, requested=4) == 3


def test_parallel_mutation_preserves_order_and_counts(monkeypatch):
    rtl = (
        "module t; wire a = b && c; "
        "always @(posedge clk) if (!rst_n) q<=0; else q<=q+1'b1; "
        "endmodule"
    )
    tb = "module tb; endmodule"
    n = {"i": 0}

    def fake_verify(sources, tb_sv, **kwargs):
        n["i"] += 1
        if n["i"] == 1:
            return {"ok": True}
        return {"ok": False, "reason": "sim_fail"}

    monkeypatch.setattr("dv_mutation.verify_testbench", fake_verify)
    monkeypatch.setattr("dv_mutation.verilator_bin", lambda: "verilator")
    r = mutation_test(rtl, tb, workers=4)
    assert r["baseline_pass"] is True
    assert r["workers"] > 1
    assert r["killed"] == r["total"]
    assert r["survived"] == 0
    names = [m["mutant"] for m in r["mutants"]]
    assert names == [nm for nm, _ in generate_mutants(rtl)[:6]]
    assert all(m["status"] == "killed" for m in r["mutants"])
