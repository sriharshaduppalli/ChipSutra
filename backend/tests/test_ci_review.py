"""PR diff review worker (offline)."""
from ci_review import review_diff, _format_comment


DIFF = """diff --git a/tb.sv b/tb.sv
index 1111111..2222222 100644
--- a/tb.sv
+++ b/tb.sv
@@ -0,0 +1,10 @@
+module tb;
+  int beats;
+  function bit check(); return 1; endfunction
+  initial begin
+    beats++;
+    $display("ok");
+  end
+endmodule
"""


def test_review_diff_flags_noop_scoreboard():
    r = review_diff(DIFF, run_verilator=False)
    titles = {f["title"] for f in r["findings"]}
    assert "No-op scoreboard" in titles
    assert "beats++ smoke" in titles
    assert "tb.sv" in r["files"]
    assert "ChipSutra CI review" in r["comment"]
    assert "NEEDS ATTENTION" in r["comment"]


def test_review_empty_diff_is_ok():
    r = review_diff("", run_verilator=False)
    assert r["ok"] is True
    assert r["files"] == []


def test_comment_mentions_not_signoff():
    text = _format_comment(["dut.sv"], [], [], True)
    assert "not" in text.lower() and "sign-off" in text.lower()


def test_review_sva_diff_flags_unlabeled():
    diff = """diff --git a/props.sv b/props.sv
index 111..222 100644
--- a/props.sv
+++ b/props.sv
@@ -0,0 +1,6 @@
+module props;
+  assert property (@(posedge clk) enable |-> 1'b1);
+endmodule
"""
    r = review_diff(diff, run_verilator=False)
    titles = " ".join(f["title"] for f in r["findings"])
    assert "SVA" in titles
    assert r["ok"] is True

