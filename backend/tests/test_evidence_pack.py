"""Community evidence pack (manifest + ZIP)."""
from evidence_pack import evidence_document, write_evidence_zip


def test_evidence_document_shape():
    doc = evidence_document(
        dut_name="counter_en",
        protocol="counter",
        sim_pass=True,
        mutation={"kill_rate": 1.0, "killed": 3, "survived": 0, "total": 3, "baseline_pass": True},
        analysis={"protocol": "counter", "support_tier": "supported", "timing_style": "sequential"},
        tool_versions={"verilator": "5.x"},
    )
    assert doc["chipsutra_evidence"] == "1.0"
    assert doc["sim_pass"] is True
    assert doc["mutation"]["killed"] == 3
    assert doc["analysis"]["protocol"] == "counter"
    assert "verilator" in doc["tool_versions"]


def test_write_evidence_zip(tmp_path):
    dest = tmp_path / "pack.zip"
    doc = evidence_document(dut_name="fifo", protocol="fifo", sim_pass=True)
    path = write_evidence_zip(
        dest,
        document=doc,
        files={"tb.sv": "module t; endmodule\n", "sim.log": "PASS\n"},
    )
    assert path.is_file()
    import zipfile

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert "evidence.json" in names
        assert "tb.sv" in names
        assert "sim.log" in names


def test_evidence_zip_bytes_roundtrip():
    from evidence_pack import evidence_zip_bytes

    blob = evidence_zip_bytes(
        document=evidence_document(dut_name="x", sim_pass=False),
        files={"tb.sv": "module t; endmodule\n"},
    )
    assert blob[:2] == b"PK"
