from tb_review import review_generated_tb


def test_flags_seen_plus_and_noop_constraint():
    sv = """
    module tb;
      int seen;
      initial begin seen++; end
      class t; rand bit a; constraint legal_c { 1; } endclass
      function bit check(); return 1; endfunction
    endmodule
    """
    r = review_generated_tb(sv)
    titles = " ".join(f["title"] for f in r["findings"])
    assert "Traffic counter" in titles
    assert "noop constraint" in titles.lower() or "1;" in titles
    assert r["fake_golden"] is True
    assert r["verdict"] == "reject"


def test_missing_dut_ports():
    sv = "module foo_tb; foo dut(.clk(clk)); endmodule"
    r = review_generated_tb(sv, ports=[{"name": "enable"}, {"name": "count"}])
    assert "enable" in r["missing_ports"]
    assert r["verdict"] == "reject"
