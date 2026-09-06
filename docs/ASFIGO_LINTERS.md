# AsFigo tools — ChipSutra integration

ChipSutra **does not vendor** [AsFigo](https://github.com/AsFigo) repos. Clone them yourself, point env vars, and ChipSutra wraps them. Native regex lint still always runs.

Book listings from [ft_sva_BenCohen](https://github.com/AsFigo/ft_sva_BenCohen) are **catalogued by filename only** — ChipSutra never pastes those `.sv` bodies into Generate.

## PATH linters (CLI)

| Tool | Repo | Env | ChipSutra hook |
|------|------|-----|----------------|
| SVALint | [SVALint](https://github.com/AsFigo/SVALint) | `CHIPSUTRA_SVALINT` | Generate assertions / formal_hints |
| FCOVLint | [FCOVLint](https://github.com/AsFigo/FCOVLint) | `CHIPSUTRA_FCOVLINT` | Generate covergroups |
| SVCK | [svck](https://github.com/AsFigo/svck) | `CHIPSUTRA_SVCK` | Generate testbench (style/encapsulation) |
| FPGALint | [FPGALint](https://github.com/AsFigo/FPGALint) | `CHIPSUTRA_FPGALINT` | Generate spec2rtl (repo is a stub; native `fpga_lint.py` always runs) |
| pyslint | [pyslint](https://github.com/AsFigo/pyslint) | `CHIPSUTRA_PYSLINT` | PATH hook |
| yoYoLint | [yoYoLint](https://github.com/AsFigo/yoYoLint) | `CHIPSUTRA_YOYOLINT` | PATH hook |

Needs [Verible](https://github.com/chipsalliance/verible) for SVALint / FCOVLint / SVCK.

```bash
export CHIPSUTRA_SVALINT=/path/to/SVALint/bin/svalint.py
export CHIPSUTRA_FCOVLINT=/path/to/FCOVLint/bin/fcovlint.py
export CHIPSUTRA_SVCK=/path/to/svck/bin/svck.py
export CHIPSUTRA_ASFIGO=0   # disable all CLI wrappers
```

## Extra packs (directories)

| Pack | Repo | Env | How ChipSutra uses it |
|------|------|-----|------------------------|
| Fast-Track SVA | [ft_sva_BenCohen](https://github.com/AsFigo/ft_sva_BenCohen) | `CHIPSUTRA_FT_SVA_DIR` | Chapter/example **names** in Generate notes + `learning.sva.ft_sva`. Buy/read the [book](https://payhip.com/b/7HvMk); do not copy listings. |
| IVL_UVM | [ivl_uvm](https://github.com/AsFigo/ivl_uvm) | `CHIPSUTRA_IVL_UVM` or `IVL_UVM_HOME` | `CHIPSUTRA_SIM_ADAPTER=iverilog` → `iverilog -t null -g2012 -I $IVL_UVM/ivl_uvm_src`. Limited messaging/test — **not** Accellera UVM, **not** Verilator UVM sign-off. Closed-loop sim stays Verilator Pure SV. |
| MathLib | [MathLib](https://github.com/AsFigo/MathLib) | `CHIPSUTRA_MATHLIB_DIR` | Spec→RTL hint to `import` `asfigo_MathLib_pkg` for **sim-only** real/vector math. Do not inline the library. No `real` in FPGA RTL. |

`GET /api/health` → `asfigo` (CLIs + `packs`). Native always-on: `sva_lint.py`, `fcov_lint.py`, `fpga_lint.py`.

## Default sim

Leave `CHIPSUTRA_SIM_ADAPTER` unset (Verilator). Icarus is opt-in.
