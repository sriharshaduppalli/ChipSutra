# Liberty files for OpenSTA (Community)

ChipSutra runs **OpenSTA** when `sta` is on PATH. Timing numbers need a Liberty (`.lib`) file.

This is **not** foundry sign-off. PrimeTime / Tempus / a process PDK stay with your foundry flow.

## Bundled demo liberty

`backend/fixtures/chipsutra_demo.lib` is a tiny original library (INV, BUF, NAND2, DFF) plus `backend/fixtures/inv_chain.v` for smoke.

- STA with **no uploaded .lib** uses this demo file when `sta` exists (`engine=opensta_demo`).
- Cells must match the netlist. Yosys `synth_netlist*.v` usually does **not** map to INV/BUF unless you mapped to this library.
- For a real STA smoke: synthesize against this liberty, or upload your own `.lib`.

## Sky130 (user-supplied, never vendored)

ChipSutra does **not** ship the SkyWater PDK. Install it yourself, then point STA at a liberty:

1. Follow [google/skywater-pdk](https://github.com/google/skywater-pdk) / [open_pdks](https://github.com/RTimothyEdwards/open_pdks) (or a packaged `open_pdks` distro).
2. Upload a typical-corner `.lib` (for example `sky130_fd_sc_hd__tt_025C_1v80.lib`) on the project Files pane.
3. Select that file in the STA panel Liberty dropdown.
4. Provide an SDC (or use the OpenSTA scaffold) and a mapped netlist.

Do not copy foundry `.lib` files into this git repo.

## Mock vs real

| Condition | Engine |
|-----------|--------|
| `sta` missing | `mock` |
| `sta` present, no user liberty | `opensta_demo` (bundled INV/BUF/NAND2/DFF) |
| `sta` + user `.lib` | `opensta` |
