/** Parse generated TB SV into a reviewable architecture graph. No LLM. */

function all(re, s) {
  const out = [];
  const r = new RegExp(re.source, re.flags.includes("g") ? re.flags : `${re.flags}g`);
  let m;
  while ((m = r.exec(s))) out.push(m[1] || m[0]);
  return out;
}

function roleOf(name) {
  const n = String(name || "").toLowerCase();
  if (n.includes("scoreboard") || n.endsWith("_sb")) return "scoreboard";
  if (n.includes("generator") || n.endsWith("_gen")) return "generator";
  if (n.includes("driver")) return "driver";
  if (n.includes("monitor")) return "monitor";
  if (n.includes("sequencer") || n.endsWith("_sqr")) return "sequencer";
  if (n.includes("agent")) return "agent";
  if (n.endsWith("_env") || n.includes("environment") || n.endsWith("_env_c")) return "env";
  if (n.endsWith("_test") || n.endsWith("_test_c")) return "test";
  if (n.includes("adapter")) return "ral_adapter";
  if (n.includes("csr_seq") || n.endsWith("_reg_block") || n.includes("ral")) return "ral";
  if (n.includes("txn") || n.includes("seq_item") || n.includes("transaction") || n.endsWith("_item")) return "txn";
  return "class";
}

function firstRole(names, role) {
  return names.find((n) => roleOf(n) === role) || null;
}

function node(id, label, role, present, note = "") {
  return { id, label: present ? label : `(missing ${role})`, role, present: !!present, note };
}

export function analyzeTbArchitecture(sv, methodologyHint = "") {
  const body = sv || "";
  const classes = all(/\bclass\s+(\w+)/gi, body);
  const ifaces = all(/\binterface\s+(\w+)/gi, body);
  const modules = all(/\bmodule\s+(\w+)/gi, body);
  const mailboxes = all(/\bmailbox\s*(?:#\s*\([^)]+\))?\s+(\w+)/gi, body);

  const uvm = /\b(uvm_pkg|uvm_component|`uvm_|run_test\s*\()/i.test(body);
  const ovm = /\b(ovm_pkg|ovm_component|`ovm_)/i.test(body) && !uvm;
  const vmm = /\b(vmm_|`vmm_)/i.test(body) && !uvm;
  const hint = String(methodologyHint || "").toLowerCase();
  let methodology = "procedural";
  if (uvm || hint === "uvm") methodology = "uvm";
  else if (ovm || hint === "ovm") methodology = "ovm";
  else if (vmm || hint === "vmm") methodology = "vmm";
  else if (classes.length || ifaces.length) methodology = "sv";

  const dutInst = body.match(/\b(\w+)\s*(?:#\s*\([^;]*\))?\s+(dut|u_dut|i_dut)\s*[\(\n]/i);
  let dut = dutInst ? dutInst[1] : null;
  if (!dut) {
    const tbMods = modules.filter((m) => /_tb$|_top$/i.test(m));
    const others = modules.filter((m) => !tbMods.includes(m));
    dut = others[0] || modules[0] || "dut";
  }
  const top = modules.find((m) => /_tb$/i.test(m)) || modules[modules.length - 1] || "tb";

  const byRole = {
    interface: ifaces[0] || null,
    txn: firstRole(classes, "txn"),
    generator: firstRole(classes, "generator"),
    driver: firstRole(classes, "driver"),
    monitor: firstRole(classes, "monitor"),
    scoreboard: firstRole(classes, "scoreboard"),
    sequencer: firstRole(classes, "sequencer"),
    agent: firstRole(classes, "agent"),
    env: firstRole(classes, "env"),
    test: firstRole(classes, "test"),
    ral: firstRole(classes, "ral") || (/\b(uvm_reg_block|frontdoor_walk|UVM_FRONTDOOR)\b/.test(body) ? "reg_block" : null),
  };
  const hasVif = /\bvirtual\s+\w+/.test(body);
  const hasAp = /\buvm_analysis_(?:port|imp|export)\b/i.test(body);
  const hasRun = /\brun_test\s*\(/i.test(body);
  const hasCfg = /\buvm_config_db\s*#/.test(body);
  const vip = /require_user_vip|attach user vip|no invented pin/i.test(body);
  const ral = /\b(uvm_reg_block|frontdoor_walk|UVM_FRONTDOOR)\b/.test(body) || !!byRole.ral;

  const expected =
    methodology === "uvm"
      ? [
          ["test", "test"],
          ["env", "env"],
          ["agent", "agent"],
          ["sequencer", "sequencer"],
          ["driver", "driver"],
          ["monitor", "monitor"],
          ["scoreboard", "scoreboard"],
          ["txn", "sequence item"],
          ["if", "interface"],
          ["dut", "DUT instance"],
          ["top", "TB top"],
        ]
      : methodology === "sv"
        ? [
            ["test", "test"],
            ["env", "env"],
            ["generator", "generator"],
            ["driver", "driver"],
            ["monitor", "monitor"],
            ["scoreboard", "scoreboard"],
            ["txn", "transaction"],
            ["if", "interface"],
            ["dut", "DUT instance"],
            ["top", "TB top"],
          ]
        : [
            ["dut", "DUT instance"],
            ["top", "TB top"],
          ];

  const present = {
    test: !!byRole.test,
    env: !!byRole.env,
    agent: !!byRole.agent,
    sequencer: !!byRole.sequencer || (methodology === "uvm" && body.includes("seq_item_port")),
    generator: !!byRole.generator,
    driver: !!byRole.driver,
    monitor: !!byRole.monitor,
    scoreboard: !!byRole.scoreboard || /\berrors\s*\+\+/.test(body),
    txn: !!byRole.txn,
    if: !!byRole.interface,
    dut: !!(dutInst || dut),
    top: modules.length > 0,
    ral,
  };

  const labels = {
    test: byRole.test || "test",
    env: byRole.env || "env",
    agent: byRole.agent || "agent",
    sequencer: byRole.sequencer || "sequencer",
    generator: byRole.generator || "generator",
    driver: byRole.driver || "driver",
    monitor: byRole.monitor || "monitor",
    scoreboard: byRole.scoreboard || "scoreboard",
    txn: byRole.txn || "txn",
    if: byRole.interface || `${dut}_if`,
    dut,
    top,
    ral: byRole.ral || "reg_block",
    vip: "user VIP",
  };

  const shown = expected.map(([id]) => id);
  if (ral) shown.push("ral");
  if (vip) shown.push("vip");

  const nodes = shown.map((id) => {
    let note = "";
    if (id === "if" && methodology === "sv" && present.if && !hasVif) note = "combo / no virtual IF (OK for some DUTs)";
    if (id === "vip") note = "Attach licensed VIP — ChipSutra stub only";
    if (id === "sequencer" && !byRole.sequencer && present.sequencer) note = "seq_item_port present (implicit sequencer)";
    return node(id, labels[id], id, present[id] !== false && (id === "vip" || id === "ral" ? true : present[id]), note);
  });

  const edges = [];
  const edge = (from, to, label, ok) => edges.push({ from, to, label, present: !!ok });
  if (methodology === "uvm") {
    edge("test", "env", "contains", present.test && present.env);
    edge("env", "agent", "contains", present.env && present.agent);
    edge("agent", "sequencer", "sqr", present.agent && present.sequencer);
    edge("agent", "driver", "drv", present.agent && present.driver);
    edge("sequencer", "driver", "seq_item", present.sequencer && present.driver);
    edge("driver", "if", hasVif ? "vif" : "pins", present.driver && present.if);
    edge("if", "dut", "ports", present.if && present.dut);
    edge("agent", "monitor", "mon", present.agent && present.monitor);
    edge("monitor", "scoreboard", hasAp ? "analysis" : "txn", present.monitor && present.scoreboard);
    if (ral) {
      edge("env", "ral", "map", true);
      edge("ral", "driver", "frontdoor", true);
    }
  } else if (methodology === "sv") {
    edge("test", "env", "run", present.test && present.env);
    edge("env", "generator", "contains", present.env && present.generator);
    edge("generator", "driver", mailboxes[0] || "mailbox", present.generator && present.driver);
    edge("driver", present.if ? "if" : "dut", "drive", present.driver);
    if (present.if) edge("if", "dut", "ports", present.dut);
    edge("env", "monitor", "contains", present.env && present.monitor);
    edge("monitor", "scoreboard", mailboxes[1] || "compare", present.monitor && present.scoreboard);
  } else {
    edge("top", "dut", "instance", present.top && present.dut);
  }
  if (vip) {
    edge("monitor", "vip", "analysis stub", true);
    edge("vip", "scoreboard", "user connect", false);
  }

  const findings = [];
  const missing = expected.filter(([id]) => !present[id]).map(([, label]) => label);
  if (!present.dut) findings.push({ severity: "error", title: "No DUT instance", hint: "Top should instantiate the user RTL by its real module name." });
  if ((methodology === "sv" || methodology === "uvm") && !present.scoreboard) {
    findings.push({ severity: "error", title: "No scoreboard", hint: "Without a checker the TB can compile and still prove nothing." });
  }
  if (methodology === "sv" && !present.generator) {
    findings.push({ severity: "warn", title: "No generator", hint: "Layered Pure SV normally has a generator feeding the driver via mailbox." });
  }
  if (methodology === "uvm" && !hasRun) {
    findings.push({ severity: "error", title: "No run_test()", hint: "UVM top must call run_test(\"...\") — ChipSutra Simulate will not execute this." });
  }
  if (methodology === "uvm" && !hasCfg) {
    findings.push({ severity: "warn", title: "No uvm_config_db vif", hint: "Driver/monitor usually get the virtual interface from config_db." });
  }
  if (vip) findings.push({ severity: "warn", title: "VIP stub — no pin golden", hint: "AXI4/PCIe/CHI-class protocol: attach your licensed VIP before sign-off." });
  if (ral) findings.push({ severity: "ok", title: "RAL / CSR map present", hint: "Frontdoor sequence uses the user map only — review offsets before vendor sim." });
  if (methodology === "sv" && present.if && !hasVif) {
    findings.push({ severity: "ok", title: "No virtual interface", hint: "Combo goldens may bind hierarchically — that is intentional for Verilator." });
  }
  if (!missing.length && !findings.some((f) => f.severity === "error")) {
    findings.unshift({
      severity: "ok",
      title: "Architecture complete",
      hint: `${methodology.toUpperCase()} stack is present. Review the scoreboard golden against the DUT.`,
    });
  } else if (missing.length) {
    findings.push({
      severity: "warn",
      title: `Missing: ${missing.join(", ")}`,
      hint: "Regenerate or repair before treating this as a reviewable TB.",
    });
  }

  const errors = findings.filter((f) => f.severity === "error").length;
  const warns = findings.filter((f) => f.severity === "warn").length;
  let verdict = "ok";
  let summary = `${methodology.toUpperCase()} layered stack looks complete`;
  if (errors) {
    verdict = "incomplete";
    summary = findings[0]?.title || "Incomplete architecture";
  } else if (warns) {
    verdict = "gaps";
    summary = `${shown.length - missing.length}/${expected.length} layers present — review gaps`;
  }

  const mermaid = [
    "flowchart TB",
    `  subgraph TB[${methodology.toUpperCase()} / ${dut}]`,
    ...nodes.map((n) => (n.present ? `    ${n.id}["${n.label}"]` : `    ${n.id}("${n.label}")`)),
    "  end",
    ...edges.map((e) => `  ${e.from} ${e.present ? "-->" : "-.->"}${e.label ? `|"${e.label}"|` : ""} ${e.to}`),
  ].join("\n");

  return {
    methodology,
    dut,
    top,
    title: `${methodology.toUpperCase()} TB — ${dut}`,
    verdict,
    summary,
    nodes,
    edges,
    findings,
    has_virtual_if: hasVif,
    has_mailbox: mailboxes.length > 0,
    has_analysis_port: hasAp,
    has_ral: ral,
    require_user_vip: vip,
    mermaid,
    classes,
    interfaces: ifaces,
    source: "generated_sv",
  };
}
