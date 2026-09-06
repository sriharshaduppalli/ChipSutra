"""Community Verilator adapter vs Enterprise stubs."""
from sim_adapter import resolve_adapter


def test_default_adapter_is_verilator():
    a = resolve_adapter()
    assert a.name == "verilator"


def test_questa_stub_is_enterprise():
    q = resolve_adapter("questa")
    assert q.name == "questa"
    assert q.available() is False
    lint = q.lint([])
    assert lint["skipped"] is True
    assert "Enterprise" in lint["reason"]
    assert "sign-off" in lint["reason"].lower()


def test_iverilog_adapter_name_and_skip():
    a = resolve_adapter("iverilog")
    assert a.name == "iverilog"
    r = a.lint([("m.sv", "module m; endmodule")])
    blob = (r.get("note") or r.get("reason") or "")
    assert "UVM" in blob or r.get("skipped") or "engine" in r


def test_ivl_uvm_alias():
    a = resolve_adapter("ivl_uvm")
    assert a.name == "iverilog"


def test_vcs_and_xcelium_stubs():
    for name in ("vcs", "xcelium"):
        a = resolve_adapter(name)
        assert a.available() is False
        assert a.name == name
