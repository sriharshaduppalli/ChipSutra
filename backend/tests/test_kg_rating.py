from kg_rating import auto_score_testbench, combine_with_feedback, aggregate_learning_report


def test_auto_score_skeleton_high():
    r = auto_score_testbench("// ok\n$urandom\n$dumpfile\nexpected = expected + 1\n", "skeleton", True, [])
    assert r["auto_score"] >= 85


def test_auto_score_lint_ok_llm_can_reach_solid():
    sv = "module t; always #5 clk=~clk; $urandom; $dumpfile; expected = expected + 1; endmodule"
    r = auto_score_testbench(sv, "llm", True, [])
    assert r["auto_score"] >= 80
    assert "independent_golden" in r["auto_reasons"]


def test_auto_score_lint_fail_lowers():
    r = auto_score_testbench("module x; endmodule", "llm", False, ["bad_or_missing_clock"])
    assert r["auto_score"] < 60


def test_feedback_adjusts():
    assert combine_with_feedback(70, 1) > 70
    assert combine_with_feedback(70, -1) < 70


def test_aggregate_improving_trend():
    docs = []
    for i, s in enumerate([40, 45, 50, 70, 80, 90]):
        docs.append({"engine": "skeleton", "learning": {"final_score": s, "lint_ok": True}, "created_at": f"2026-01-0{i+1}"})
    # API passes newest-first
    docs = list(reversed(docs))
    rep = aggregate_learning_report(docs)
    assert rep["sample_size"] == 6
    assert rep["kg_learning_score"] is not None
    assert rep["trend"] == "improving"
    assert rep["grade"] in ("A", "B", "C", "D", "F")
