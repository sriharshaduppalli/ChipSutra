# Backend knowledge index (RAG)

Text files here are chunked by `##` headings and injected into **Generate** prompts when `RAG_ENABLED=true` (default).

**Vector rerank (optional):** `pip install -r requirements-rag.txt` enables sentence-transformers (default model `BAAI/bge-small-en-v1.5`). Without it, RAG uses hashed-TFIDF. Bakeoff: `python scripts/eval_rag_embedders.py` → `storage/rag_embedder_trial.md`.

Optional AsFigo SVALint / FCOVLint (not vendored): [docs/ASFIGO_LINTERS.md](../../docs/ASFIGO_LINTERS.md).

| File | Source |
|------|--------|
| `vlsi_protocols_compact.txt` | ChipSutra-VLSI-LLM `prompts/` (v1.2+ multi-protocol) |
| `protocol_tb_guidance.txt` | ChipSutra — per-protocol/version TB emit rules (APB3/4, AXI4-Lite, FIFO FWFT, combo mux, …) |
| `protocol_vip_axi_lite.txt` | ChipSutra — AXI4-Lite VIP emit; distilled from ARM IHI 0022L (not copied) |
| `protocol_vip_apb.txt` | ChipSutra — APB3/APB4 VIP emit; distilled from ARM IHI 0024E (not copied) |
| `protocol_vip_ahb.txt` | ChipSutra — AHB-Lite/AHB5 VIP emit; distilled from ARM IHI 0033C (not copied) |
| `protocol_vip_axis.txt` | ChipSutra — AXI4-Stream VIP emit |
| `protocol_vip_serial.txt` | ChipSutra — SPI modes 0–3 / I2C master·10-bit / UART TX+RX knobs |
| `protocol_vip_can.txt` | ChipSutra — CAN/CAN-FD idle+SOF smoke; never invent bit-time |
| `protocol_vip_i3c.txt` | ChipSutra — I3C I2C-compatible + CCC/IBI only if ports exist |
| `protocol_vip_axi_full.txt` | ChipSutra — AXI4 burst / ACE / CHI require user VIP |
| `protocol_vip_anatomy.txt` | ChipSutra — VIP = driver + monitor + checker + coverage |
| `protocol_vip_commercial.txt` | ChipSutra — commercial VIP catalog (integrate, do not copy) |
| `protocol_vip_scale.txt` | ChipSutra — block ≠ ip ≠ processor ≠ subsystem ≠ SoC ≠ chiplet |
| `protocol_vip_offchip.txt` | ChipSutra — PCIe / CXL TLP outline; user VIP for PHY/LTSSM |
| `protocol_vip_d2d.txt` | ChipSutra — UCIe / BoW / AIB chiplet bounds |
| `protocol_vip_memory.txt` | ChipSutra — DDR/LPDDR/HBM/DFI/SRAM; never invent JEDEC |
| `protocol_vip_netio.txt` | ChipSutra — Ethernet / USB / MIPI pin smoke + VIP bounds |
| `protocol_vip_debug.txt` | ChipSutra — JTAG / SWD / DFT; no invented TAP maps |
| `protocol_vip_ral.txt` | ChipSutra — RAL emit only from user csr_list (no invented CSRs) |
| `dv_config.example.json` | Example CHIPSUTRA_DV_CONFIG / Generate `dv_config` |
| `protocol_vip_simple.txt` | ChipSutra — FIFO/mux/ALU/counter/parity emit |
| `protocol_vip_riscv.txt` | ChipSutra — RV32I directed smoke + user memory/CSR map (no auto-RAL) |
| `protocol_vip_onchip.txt` | ChipSutra — Wishbone / Avalon-MM / TileLink / FSM emit |
| `vlsi_soc_dft_power.txt` | ChipSutra-VLSI-LLM — SoC / DFT / UPF / CDC |
| `vlsi_verification_glossary.txt` | ChipSutra-VLSI-LLM — DV/HDL glossary |
| `verification_techniques.txt` | ChipSutra — sim / formal / emulation / FPGA proto (ChipVerify techniques map, not copied) |
| `verification_stages.txt` | ChipSutra — block / subsystem / SoC stages, regression, bug cost, handoff |
| `uvm_patterns.txt` | ChipSutra — UVM / SV TB patterns |
| `sv_vs_uvm_tb_map.txt` | ChipSutra — Pure SV ↔ UVM roles, phases, TLM, objections, factory, coverage, reuse, scale |
| `uvm_basics_intro.txt` | **ChipVerify UVM Tutorial intro** — what/why, OVM→UVM, 7 pillars, prereqs |
| `uvm_class_hierarchy.txt` | **ChipVerify UVM Introduction** — component vs object, hierarchy, TLM/sequence map |
| `uvm_installation.txt` | **ChipVerify UVM Installation** — library not app, Accellera/`$UVM_HOME`, Verilator limits |
| `uvm_hello.txt` | **ChipVerify Hello UVM!** — minimal test+env+`run_test`, factory, `` `uvm_info `` |
| `uvm_class_library.txt` | **ChipVerify UVM Class Library** — emit-oriented core class index |
| `uvm_first_tb_dut.txt` | **ChipVerify Build First TB** — `reg_block` + `reg_if` chapter DUT contract |
| `uvm_object.txt` | **ChipVerify uvm_object** — factory, `` `uvm_object_utils ``, new vs create |
| `uvm_transaction.txt` | **ChipVerify transaction class** — `uvm_sequence_item`, fields, constraints |
| `uvm_component.txt` | **ChipVerify uvm_component** — hierarchy, build_phase, parent/new |
| `uvm_driver.txt` | **ChipVerify uvm_driver** — config_db vif, get_next_item/item_done, pin timing |
| `uvm_monitor.txt` | **ChipVerify uvm_monitor** — passive sample, analysis_port.write, read latency |
| `uvm_subscriber.txt` | **ChipVerify uvm_subscriber** — analysis_export, write(), coverage connect |
| `uvm_sequencer.txt` | **ChipVerify uvm_sequencer** — pull model, port→export connect |
| `uvm_sequence.txt` | **ChipVerify uvm_sequence** — body(), start_item/finish_item, start() |
| `uvm_sequence_usage.txt` | **ChipVerify use a sequence** — objections, default_sequence, start vs `uvm_do |
| `uvm_scoreboard.txt` | **ChipVerify scoreboard** — analysis_imp, reference model, compare |
| `uvm_agent.txt` | **ChipVerify uvm_agent** — active/passive, build+connect VIP |
| `uvm_env.txt` | **ChipVerify uvm_env** — owns agent+scoreboard, mon→sb connect |
| `uvm_test.txt` | **ChipVerify uvm_test** — build env, start sequence, derivative tests |
| `uvm_tb_top.txt` | **ChipVerify TB top** — IF+DUT, config_db set, run_test, waves |
| `uvm_base_classes.txt` | **ChipVerify UVM Base Classes** — void/object/report/component/root chain |
| `uvm_root.txt` | **ChipVerify uvm_root** — uvm_top singleton, orphans, find, verbosity |
| `uvm_object_pack.txt` | **ChipVerify pack/unpack** — bit/byte/int streams, do_pack, return=bitcount |
| `uvm_object_compare.txt` | **ChipVerify object compare** — compare/do_compare, field macros, nested objects |
| `uvm_object_print.txt` | **ChipVerify object print** — print/do_print/sprint/convert2string |
| `uvm_object_copy.txt` | **ChipVerify object copy/clone** — copy/do_copy/clone, deep nested copy |
| `uvm_utility_field_macros.txt` | **ChipVerify utility & field macros** — object/component utils, flags, radix |
| `uvm_field_macros.txt` | **ChipVerify field macros** — type catalog, flags, nested object/queue print |
| `uvm_phases.txt` | **ChipVerify UVM Phases** — build/connect/run/cleanup, top-down vs bottom-up |
| `uvm_objection.txt` | **ChipVerify UVM Objection** — raise/drop, drain, sequence auto-objection |
| `uvm_user_phases.txt` | **ChipVerify user-defined phases** — custom phase class, domain schedule insert |
| `uvm_factory_override.txt` | **ChipVerify factory override** — type/instance override, create vs new |
| `uvm_configure_components.txt` | **ChipVerify configure components** — knobs, config_db vs resource_db, cfg class |
| `uvm_resource_db.txt` | **ChipVerify resource database** — pool/scope, config_db vs resource_db, vif |
| `uvm_config_db.txt` | **ChipVerify uvm_config_db** — set/get/exists, cfg objects, vif best practices |
| `uvm_config_db_examples.txt` | **ChipVerify config_db examples** — path match matrix, TRACE debug |
| `uvm_tlm.txt` | **ChipVerify UVM TLM intro** — transactions, ports/exports, smoke connect map |
| `uvm_tlm_blocking_put.txt` | **ChipVerify TLM blocking put** — put_port / put_imp, blocking put task |
| `uvm_tlm_blocking_get.txt` | **ChipVerify TLM blocking get** — get_port / get_imp, pull semantics |
| `uvm_tlm_fifo.txt` | **ChipVerify uvm_tlm_fifo** — put/get exports, depth, rate decoupling |
| `uvm_tlm_example.txt` | **ChipVerify TLM hierarchy example** — nested FIFO, port/export forward |
| `uvm_tlm_analysis.txt` | **ChipVerify analysis port** — write() broadcast, subscriber/scoreboard |
| `uvm_tlm_sockets.txt` | **ChipVerify TLM sockets** — initiator/target, b_transport (TLM2) |
| `uvm_tlm_decl.txt` | **ChipVerify TLM `_decl` macros** — multi put/analysis imps, write_SFX |
| `uvm_tlm_nonblocking_put.txt` | **ChipVerify TLM nonblocking put** — try_put / can_put |
| `uvm_tlm_port_export_imp.txt` | **ChipVerify port/export/imp chains** — hierarchical TLM connect patterns |
| `uvm_tlm_nonblocking_get.txt` | **ChipVerify TLM nonblocking get** — try_get / can_get |
| `uvm_sequence_start.txt` | **ChipVerify seq.start()** — call order, call_pre_post, parent_sequence |
| `uvm_sequence_macros.txt` | **ChipVerify sequence macros** — uvm_do expand, skips pre/post_body |
| `uvm_do.txt` | **ChipVerify `uvm_do*` catalog** — do/with/pri/on variants |
| `uvm_send.txt` | **ChipVerify `uvm_send*` / create** — pre-existing items, no auto-create |
| `uvm_virtual_sequence.txt` | **ChipVerify virtual sequence** — multi-sequencer coordination |
| `uvm_virtual_sequencer.txt` | **ChipVerify virtual sequencer** — handle holder, no driver |
| `uvm_sequence_library.txt` | **ChipVerify sequence library** — RAND/RANDC modes, registration |
| `uvm_sequence_arbitration.txt` | **ChipVerify sequence arbitration** — FIFO/RANDOM/STRICT/WEIGHTED |
| `uvm_reporting_classes.txt` | **ChipVerify reporting classes** — why macros beat $display |
| `uvm_reporting_functions.txt` | **ChipVerify reporting functions** — macros, verbosity enum |
| `uvm_printer.txt` | **ChipVerify uvm_printer** — table/tree/line, knobs |
| `uvm_comparer.txt` | **ChipVerify uvm_comparer** — compare policy, MISCMP, result |
| `uvm_callback.txt` | **ChipVerify uvm_callback** — register_cb / do_callbacks |
| `uvm_event.txt` | **ChipVerify uvm_event** — wait_trigger vs wait_ptrigger |
| `uvm_event_pool.txt` | **ChipVerify uvm_event_pool** — named global event lookup |
| `uvm_ral.txt` | **ChipVerify RAL intro** — regs/blocks/maps, why RAL |
| `uvm_ral_classes.txt` | **ChipVerify RAL classes** — field/reg/block, desired/mirrored |
| `uvm_ral_env.txt` | **ChipVerify RAL env** — adapter, predictor, reg_env |
| `uvm_ral_connect.txt` | **ChipVerify RAL connect** — set_sequencer + mon→predictor |
| `uvm_ral_backdoor.txt` | **ChipVerify RAL backdoor** — HDL paths, UVM_BACKDOOR |
| `uvm_ral_example.txt` | **ChipVerify RAL example** — APB traffic CSR end-to-end map |
| `uvm_get_next_item.txt` | **ChipVerify get_next_item** — driver/sequencer handshake |
| `uvm_transaction_object.txt` | **ChipVerify transaction object** — sequence_item recipe |
| `uvm_get_put.txt` | **ChipVerify get/put** — alternate handshake + get_response |
| `uvm_hdl_access.txt` | **ChipVerify HDL access** — deposit/force/read DPI |
| `uvm_singleton.txt` | **ChipVerify singleton** — static get() shared instance |
| `uvm_guide_reusable_vip.txt` | **ChipVerify reusable VIP guide** — agent/seq/factory rules |
| `uvm_guide_using_vip.txt` | **ChipVerify using UVCs guide** — env integrate / sequences |
| `uvm_users_guide_emit.txt` | ChipSutra — Accellera UVM UG 1.2 (prefer over 1.1) emit map; not copied |
| `ovm_vmm_interop_emit.txt` | ChipSutra — VIP-1.0 interconnected model + OVM-VMM AVT adapters (catalog only) |
| `uvm_tb_example_pattern.txt` | **ChipVerify TB example** — pattern detector end-to-end |
| `uvm_tb_example1.txt` | **ChipVerify TB example 1** — reg/memory UVM stack |
| `uvm_tb_example2.txt` | **ChipVerify TB example 2** — addr-range switch |
| `sva_patterns.txt` | ChipSutra — SVA patterns |
| `sva_fast_track.txt` | ChipSutra — Fast-Track SVA study map (optional ft_sva_BenCohen catalog) |
| `sv_mathlib_pack.txt` | ChipSutra — MathLib import bounds (sim-only real) |
| `fpga_lint_notes.txt` | ChipSutra — FPGA synth pitfalls |
| `ivl_uvm_notes.txt` | ChipSutra — Icarus + IVL_UVM limits |
| `sim_debug_playbook.txt` | ChipSutra — sim triage |
| `covergroup_patterns.txt` | ChipSutra-VLSI-LLM `prompts/` (synced) — bins/cross/closure |
| `kg_sv_uvm_learning.txt` | **Knowledge graph curriculum** — SV/UVM syntax, reuse, random, scale (L1–L4) |
| `sv_uvm_syntax_core.txt` | Expanded SV/UVM syntax reference for RAG “training” |
| `dv_tb_templates.txt` | Universal solid TB templates (smoke / random / CRV / layered / UVM) |
| `verification_methodologies_curriculum.txt` | SV/UVM/OVM/VMM ladder + TB fundamentals (curriculum map cites [ChipVerify SV](https://chipverify.com/tutorials/systemverilog)) |
| `sv_constraints_patterns.txt` | Deep CRV constraints (`rand`/`dist`/`soft`/`foreach`) |
| `sv_interfaces_patterns.txt` | Interfaces, modports, clocking blocks, virtual IF |
| `sv_oop_classes_patterns.txt` | Classes / OOP (UVM prerequisite) |
| `sv_arrays_collections_patterns.txt` | Packed/unpacked, queues, dynamic, associative |
| `sv_threads_ipc_patterns.txt` | fork/join, events, semaphore, mailbox |
| `sv_randomization_patterns.txt` | `$urandom`, randcase, seeds, coverage-driven random |
| `sv_datatypes_control_patterns.txt` | 2/4-state types, loops, case equality |
| `sv_advanced_features_patterns.txt` | **package/import**, DPI, callbacks, macros, program, scope `::`, local/protected |
| `sv_functions_patterns.txt` | **functions** (no time, ANSI args, pass-by-value vs `ref`) |
| `oss_eda_lab_flow.txt` | **ChipVerify Lab-style OSS flow** (Verilator/Icarus, Yosys+SkyWater, OpenSTA) vs ChipSutra |
| `sv_quick_refresher.txt` | **ChipVerify Quick Refresher** index + synth golden rules / pitfalls |
| `sv_fundamentals_must_know.txt` | **Must-know SV pillars** for every Generate (types→SVA) |
| `layered_tb_components.txt` | **DUT/DUV, IF, gen/drv/mon/sb/env/test, abstraction** (ChipVerify-style roles) |
| `sv_plusargs_patterns.txt` | **`$test$plusargs` / `$value$plusargs`** (ChipVerify CLI knobs; +SEED/+N) |
| `sv_file_ops_patterns.txt` | **`$fopen`/`$fdisplay`/`$fgets`/`$feof`/`$fscanf`**, modes, MCD |
| `sv_tb_example_reg_ctrl.txt` | **ChipVerify TB Example 1** map (reg_ctrl / ready / ref scoreboard) |
| `sv_tb_example_switch.txt` | **ChipVerify TB Example 2** map (switch / generator / semaphore / route SB) |
| `sv_tb_example_adder.txt` | **ChipVerify TB Example Adder** (combo DUT / TB clk / a+b golden / bug inject) |
| `covergroup_patterns.txt` | Functional coverage bins/cross/closure (deep) |
| `sva_patterns.txt` | Immediate/concurrent SVA + formal-friendly style (deep) |

Machine-readable graph + learning cadence: [`kg/sv_uvm_knowledge_graph.json`](kg/sv_uvm_knowledge_graph.json), [`kg/LEARNING_CURRICULUM.md`](kg/LEARNING_CURRICULUM.md).

**Learning score API:** `GET /api/kg/learning-score` · feedback `POST /api/generations/{id}/feedback` with `{ "rating": 1|-1 }`.

`vlsi_system.txt` (if present) is **ignored by RAG** — SYSTEM text lives inline in Modelfiles.

Refresh LLM-owned files after upstream updates:

```bash
./scripts/sync-vlsi-llm.sh
# or: .\scripts\sync-vlsi-llm.ps1 -SourceRepo <path-to-ChipSutra-VLSI-LLM>
```

`golden/` holds RTL fixtures for tests (not sent to RAG).

**Note:** No model “knows all VLSI” by weights alone. Coverage = Modelfile appendix (v1.2) + this RAG corpus + user RTL. Never invent ports/timing; prefer user specs.
