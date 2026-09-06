from generation_persist import generation_artifact_meta


def test_tb_sv_and_uvm_names():
    kind, name = generation_artifact_meta("testbench", "counter_en", "sv")
    assert kind == "tb"
    assert name == "counter_en_tb.sv"
    kind, name = generation_artifact_meta("testbench", "counter_en", "uvm")
    assert kind == "tb"
    assert name == "counter_en_uvm_tb.sv"


def test_sva_and_cover_and_unsafe_dut():
    kind, name = generation_artifact_meta("assertions", "my-dut")
    assert kind == "sva" and name == "my_dut_sva.sv"
    kind, name = generation_artifact_meta("covergroups", "alu4")
    assert kind == "cover" and name == "alu4_cg.sv"
    kind, name = generation_artifact_meta("unknown_mod", "x")
    assert kind == "artifact"
