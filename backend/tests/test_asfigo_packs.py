"""AsFigo extra packs: catalog names only, never ingest book SV."""
from pathlib import Path

from asfigo_packs import ft_sva_catalog, mathlib_status, ivl_uvm_status, prompt_block, pack_status


def test_ft_sva_catalog_names_only(tmp_path, monkeypatch):
    ch = tmp_path / "fast_sva" / "ch1"
    ch.mkdir(parents=True)
    (ch / "req_ack.sv").write_text("DO NOT COPY THIS BOOK LISTING\n", encoding="utf-8")
    monkeypatch.setenv("CHIPSUTRA_FT_SVA_DIR", str(tmp_path))
    cat = ft_sva_catalog()
    assert cat["available"] is True
    assert "ch1" in cat["chapters"]
    assert any("req_ack.sv" in e for e in cat["examples"])
    block = prompt_block(module="assertions")
    assert "Do not copy example file bodies" in block
    assert "DO NOT COPY THIS BOOK LISTING" not in block


def test_mathlib_and_ivl_status(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "asfigo_MathLib_pkg.sv").write_text("package x; endpackage\n", encoding="utf-8")
    monkeypatch.setenv("CHIPSUTRA_MATHLIB_DIR", str(tmp_path))
    ml = mathlib_status()
    assert ml["available"] and "asfigo_MathLib_pkg.sv" in ml["packages"]
    assert "real" in (ml["note"] or "").lower()

    ivl = tmp_path / "ivl"
    (ivl / "ivl_uvm_src").mkdir(parents=True)
    monkeypatch.setenv("CHIPSUTRA_IVL_UVM", str(ivl))
    st = ivl_uvm_status()
    assert st["available"]
    assert "Accellera" in st["note"]


def test_pack_status_shape():
    st = pack_status()
    assert set(st) >= {"ft_sva", "mathlib", "ivl_uvm"}
