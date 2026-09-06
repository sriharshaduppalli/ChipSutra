from commercial_sim_pack import (
    build_vendor_files,
    looks_like_uvm,
    uvm_refuse_message,
    uvm_test_name,
    vendor_pack_zip,
)

UVM = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_rtl_test extends uvm_test;
  `uvm_component_utils(counter_rtl_test)
endclass
module counter_rtl_tb;
  initial run_test("counter_rtl_test");
endmodule
"""


def test_looks_like_uvm_and_test_name():
    assert looks_like_uvm(UVM)
    assert uvm_test_name(UVM) == "counter_rtl_test"
    assert not looks_like_uvm("module tb; initial $finish; endmodule")


def test_vendor_files_have_scripts():
    files = build_vendor_files(
        [("counter.sv", "module counter; endmodule"), ("tb.sv", UVM)],
        tb_name="tb.sv",
        tb_sv=UVM,
    )
    assert "filelist.f" in files
    assert "run_questa.do" in files
    assert "run_vcs.sh" in files
    assert "run_xcelium.sh" in files
    assert "+UVM_TESTNAME=counter_rtl_test" in files["run_questa.do"]
    assert "counter.sv" in files["filelist.f"]
    assert "tb.sv" in files["filelist.f"]
    z = vendor_pack_zip(files)
    assert z[:2] == b"PK"
    assert "Verilator" in uvm_refuse_message("counter_rtl_test")
