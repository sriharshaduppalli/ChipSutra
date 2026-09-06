"""Optional AsFigo PATH bridge (offline: skipped when tools missing)."""
from asfigo_bridge import run_tool, tool_status


def test_tool_status_shape():
    st = tool_status()
    assert "svalint" in st and "fcovlint" in st and "svck" in st and "fpgalint" in st
    assert "enabled" in st
    assert st["svalint"]["env"] == "CHIPSUTRA_SVALINT"
    assert "packs" in st
    assert "ft_sva" in st["packs"]


def test_run_tool_skips_when_missing(monkeypatch):
    monkeypatch.delenv("CHIPSUTRA_SVALINT", raising=False)
    monkeypatch.setenv("CHIPSUTRA_ASFIGO", "1")
    r = run_tool("svalint", "module m; endmodule")
    if not r.get("skipped"):
        assert "engine" in r
        return
    assert r["skipped"] is True
    assert r["findings"] == []


def test_asfigo_env_off(monkeypatch):
    monkeypatch.setenv("CHIPSUTRA_ASFIGO", "0")
    r = run_tool("svalint", "assert property (@(posedge clk) 1);")
    assert r["skipped"] is True
