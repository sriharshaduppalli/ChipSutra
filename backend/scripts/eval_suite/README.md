# ChipSutra eval DUT samples — diverse protocols for LLM vs premium cross-check

## Designs

| id | Protocol | Ports highlight |
|----|----------|-----------------|
| counter_en | counter | clk, rst_n, enable, count[3:0] |
| sync_fifo8 | fifo | wr/rd + full/empty/count |
| sample_parity | parity | valid, data[7:0], parity, valid_out |
| mux2_8 | mux | sel, a/b[7:0], y[7:0] |
| apb_regs | apb | PSEL/PENABLE/PWRITE/PADDR/PWDATA/PRDATA/PREADY |

RTL lives in `*.sv`. Premium reference TBs in `../premium_refs/`. ChipSutra outputs land in `../chipsutra_out/` after `eval_llm_vs_premium.py`.
