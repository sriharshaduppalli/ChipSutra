"""OpenTitan/reggen HJSON → ChipSutra csr_list (no FuseSoC ralgen)."""
from pathlib import Path

from dv_user_config import parse_dv_config
from reg_hjson import csr_list_from_hjson_path, loads_hjson, registers_from_ip_hjson
from tb_ral import normalize_csr_list, render_sv_reg_model, render_uvm_ral_block

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_uart.hjson"


def test_hjson_subset_parses_bare_keys():
    doc = loads_hjson(FIXTURE.read_text(encoding="utf-8"))
    assert doc["name"] == "uart_mini"
    assert doc["regwidth"] == 32
    assert isinstance(doc["registers"], list)


def test_import_offsets_reserved_skipto_multireg():
    csrs = csr_list_from_hjson_path(FIXTURE)
    by_name = {c["name"]: c for c in csrs}
    assert by_name["INTR_STATE"]["addr"] == "0x0"
    assert by_name["CTRL"]["addr"] == "0x4"
    # reserved: 1 skips 0x8
    assert by_name["STATUS"]["addr"] == "0xc"
    assert by_name["STATUS"]["access"] == "ro"
    assert by_name["DATA0"]["addr"] == "0x20"
    assert by_name["DATA1"]["addr"] == "0x24"
    assert by_name["CTRL"]["fields"][0]["name"] == "ENABLE"
    assert by_name["INTR_STATE"]["access"] == "w1c"


def test_dv_config_ip_hjson_enables_ral():
    cfg = parse_dv_config({"ip_hjson": str(FIXTURE), "enable_ral": True}, env=False)
    names = [c["name"] for c in cfg["csr_list"]]
    assert "CTRL" in names and "STATUS" in names
    assert cfg["enable_ral"] is True
    assert cfg["hjson_imported"]
    sv = render_sv_reg_model("uart_mini", normalize_csr_list(cfg["csr_list"]))
    assert "CTRL" in sv and "STATUS" in sv
    uvm = render_uvm_ral_block("uart_mini", normalize_csr_list(cfg["csr_list"]))
    assert "uart_mini_reg_block" in uvm and "ENABLE" in uvm


def test_explicit_csr_list_wins_over_hjson():
    cfg = parse_dv_config(
        {
            "ip_hjson": str(FIXTURE),
            "csr_list": [{"name": "ONLY", "addr": "0x0", "access": "rw"}],
        },
        env=False,
    )
    assert [c["name"] for c in cfg["csr_list"]] == ["ONLY"]


def test_does_not_invent_when_no_registers_key():
    assert registers_from_ip_hjson({"name": "empty"}) == []
