"""Community sign-off board — never claims vendor sign-off."""
from signoff import build_signoff_board


def test_empty_board_is_not_signoff():
    b = build_signoff_board()
    assert b["not_vendor_signoff"] is True
    assert b["chipsutra_signoff"] == "1.0"
    names = [t["name"] for t in b["tiles"]]
    assert names == ["lint", "sim", "coverage", "cdc", "formal", "spec"]
    assert all(t["status"] == "missing" for t in b["tiles"])
    assert b["score"] == 0
    assert any("vendor" in r.lower() for r in b["residual_risk"])


def test_green_tiles_raise_score():
    b = build_signoff_board(
        generations=[
            {
                "id": "g1",
                "module": "testbench",
                "learning": {
                    "lint_ok": True,
                    "sim_pass": True,
                    "mutation": {"kill_rate": 1.0},
                },
            },
            {
                "id": "g2",
                "module": "spec2rtl",
                "learning": {"spec_checklist": {"ready": True, "grade": "solid"}},
            },
        ],
        coverage_runs=[{"overall": 80.0}],
        cdc_runs=[{"clock_count": 1, "issues": []}],
        formal_runs=[{"status": "done"}],
    )
    by = {t["name"]: t["status"] for t in b["tiles"]}
    assert by["lint"] == "pass"
    assert by["sim"] == "pass"
    assert by["coverage"] == "pass"
    assert by["cdc"] == "pass"
    assert by["formal"] == "pass"
    assert by["spec"] == "pass"
    assert b["score"] >= 90
    assert b["latest_generation_id"] == "g1"
