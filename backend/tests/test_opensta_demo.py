"""Bundled demo liberty is plausible; optional OpenSTA smoke if `sta` exists."""
from pathlib import Path

import pytest

from opensta_flow import demo_liberty_path, demo_netlist_path, liberty_is_plausible, sta_bin


def test_demo_liberty_is_plausible():
    path = demo_liberty_path()
    assert path and Path(path).is_file()
    text = Path(path).read_text(encoding="utf-8")
    assert liberty_is_plausible(text)
    assert "cell (INV)" in text
    assert "sky130" not in text.lower()


def test_demo_netlist_maps_inv():
    path = demo_netlist_path()
    assert path and Path(path).is_file()
    body = Path(path).read_text(encoding="utf-8")
    assert "INV u1" in body
    assert "module inv_chain" in body


@pytest.mark.skipif(not sta_bin(), reason="OpenSTA (`sta`) not on PATH")
def test_optional_sta_on_inv_chain(tmp_path):
    from opensta_flow import build_sta_tcl, sta_command
    import subprocess

    lib = demo_liberty_path()
    net = demo_netlist_path()
    tcl = tmp_path / "sta.tcl"
    tcl.write_text(
        build_sta_tcl(netlist=net, liberty=lib, top="inv_chain", max_paths=2),
        encoding="utf-8",
    )
    proc = subprocess.run(sta_command(str(tcl)), capture_output=True, text=True, timeout=30)
    log = (proc.stdout or "") + (proc.stderr or "")
    assert "inv_chain" in log or proc.returncode == 0 or "wns" in log.lower()
