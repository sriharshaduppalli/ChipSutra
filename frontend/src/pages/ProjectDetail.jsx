import { useCallback, useEffect, useState, useRef } from "react";
import { useParams, Link, useLocation, useNavigate } from "react-router-dom";
import { api, API, getToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import Editor from "@monaco-editor/react";
import { Upload, FileText, Cpu, Zap, Download, Loader2, X, ArrowLeft, Play, Users, Shield, GitBranch, Grid3X3, FlaskConical, Timer, Rocket, Package } from "lucide-react";
import ShareModal from "@/components/ShareModal";
import SimulationPanel from "@/components/SimulationPanel";
import CommentsPanel from "@/components/CommentsPanel";
import FormalPanel from "@/components/FormalPanel";
import CdcPanel from "@/components/CdcPanel";
import SynthPanel from "@/components/SynthPanel";
import RegressionPanel from "@/components/RegressionPanel";
import CocotbPanel from "@/components/CocotbPanel";
import StaPanel from "@/components/StaPanel";
import LabPipelinePanel from "@/components/LabPipelinePanel";
import GoldenDutImport from "@/components/GoldenDutImport";

const MODULES = [
  { id: "testbench", label: "Testbench", desc: "Layered Pure SV (IF/gen/drv/mon/sb/env/test), or UVM / OVM / VMM" },
  { id: "assertions", label: "SVA Assertions", desc: "SystemVerilog assertions for protocol/safety/liveness" },
  { id: "checkers", label: "Checkers", desc: "Reference model + protocol checkers" },
  { id: "covergroups", label: "Covergroups", desc: "Covergroups with bins, cross coverage, illegal_bins" },
  { id: "spec2rtl", label: "Spec → RTL", desc: "Generate synthesizable RTL from a spec" },
  { id: "rtl2spec", label: "RTL → Spec", desc: "Extract Markdown spec from RTL" },
  { id: "testplan", label: "Testplan", desc: "Comprehensive testplan / coverage plan" },
  { id: "coverage_holes", label: "Coverage-Hole Tests", desc: "Generate tests to close coverage holes" },
  { id: "debug", label: "Debug Analysis", desc: "Root-cause hints from simulation log" },
  { id: "formal_hints", label: "Formal Hints", desc: "SVA properties for SymbiYosys formal proofs" },
];

const TB_METHODOLOGIES = [
  { id: "sv", label: "Pure SV", hint: "LLM layered SV (IF/gen/drv/mon/sb/env/test) — no UVM" },
  { id: "uvm", label: "UVM", hint: "UVM 1.2 via ChipSutra-VLSI LLM" },
  { id: "ovm", label: "OVM", hint: "Legacy OVM via LLM" },
  { id: "vmm", label: "VMM", hint: "Legacy VMM via LLM" },
];

const DEFAULT_MODELS = [
  { provider: "ollama", model: "chipsutra-vlsi:7b", label: "ChipSutra-VLSI 7B (local)" },
  { provider: "ollama", model: "chipsutra-vlsi:3b", label: "ChipSutra-VLSI 3B (fast)" },
];

const langMap = { v: "verilog", sv: "systemverilog", vhd: "vhdl", vhdl: "vhdl", md: "markdown", txt: "plaintext", log: "plaintext", rpt: "plaintext" };

export default function ProjectDetail() {
  const { pid } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [project, setProject] = useState(null);
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [module, setModule] = useState("testbench");
  const [genMode, setGenMode] = useState("llm"); // always LLM; style hint only
  const [tbMethodology, setTbMethodology] = useState("sv"); // sv | uvm | ovm | vmm
  const [models, setModels] = useState(DEFAULT_MODELS);
  const [modelIdx, setModelIdx] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [dvConfigText, setDvConfigText] = useState("");
  const [enableRal, setEnableRal] = useState(false);
  const [dvScale, setDvScale] = useState("block");
  const [showDvConfig, setShowDvConfig] = useState(false);
  const [toolLog, setToolLog] = useState("");
  const [simFindings, setSimFindings] = useState(null);
  const [packBusy, setPackBusy] = useState(false);
  const [attachingLog, setAttachingLog] = useState(false);
  const [output, setOutput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const [showShare, setShowShare] = useState(false);
  const [showSim, setShowSim] = useState(false);
  const [showFormal, setShowFormal] = useState(false);
  const [showCdc, setShowCdc] = useState(false);
  const [showSynth, setShowSynth] = useState(false);
  const [showRegression, setShowRegression] = useState(false);
  const [showCocotb, setShowCocotb] = useState(false);
  const [showSta, setShowSta] = useState(false);
  const [showLab, setShowLab] = useState(false);
  const [regressionSeeds, setRegressionSeeds] = useState(null);
  const [regressionCoverage, setRegressionCoverage] = useState(null);
  const [pendingAutoGenerate, setPendingAutoGenerate] = useState(false);
  const [currentGenId, setCurrentGenId] = useState(null);
  const [learningInfo, setLearningInfo] = useState(null);
  const [streamStatus, setStreamStatus] = useState("");
  const [kgScore, setKgScore] = useState(null);
  const [ratingBusy, setRatingBusy] = useState(false);
  const outputRef = useRef(null);
  const generateRef = useRef(null);

  const load = useCallback(async () => {
    const { data } = await api.get(`/projects/${pid}`);
    setProject(data);
  }, [pid]);

  const attachLatestToolLog = useCallback(async () => {
    setAttachingLog(true);
    try {
      const { data } = await api.get(`/projects/${pid}/latest-tool-log`);
      if (!data.tool_log) {
        toast.info("No simulation log yet — run a simulation first");
      } else {
        setToolLog(data.tool_log);
        toast.success(`Attached log from ${data.status || "last run"}${data.truncated ? " (tail)" : ""}`);
      }
    } catch {
      toast.error("Could not load the last simulation log");
    }
    setAttachingLog(false);
  }, [pid]);

  const onSimLogReady = useCallback((logText, meta = {}) => {
    if (!logText?.trim()) return;
    setToolLog(logText);
    const failed = meta.status && meta.status !== "done" && meta.status !== "export";
    toast.success(
      failed
        ? "Sim log auto-attached for fix-loop regenerate"
        : meta.status === "export"
          ? "UVM export — use vendor pack, not Verilator"
          : "Sim log auto-attached to Generate fix-loop",
    );
    api.post("/debug/classify", { tool_log: logText, prior_output: output || "" })
      .then(({ data }) => setSimFindings(data))
      .catch(() => setSimFindings(null));
  }, [output]);

  useEffect(() => { load(); }, [load]);

  // Drop stale selections after project reload (deleted / re-uploaded files get new ids).
  useEffect(() => {
    if (!project?.files) return;
    const known = new Set(project.files.map((f) => f.id));
    setSelectedFileIds((prev) => {
      const next = prev.filter((id) => known.has(id));
      return next.length === prev.length ? prev : next;
    });
  }, [project]);

  useEffect(() => {
    if (!project?.files?.length) return;
    const wiz = new URLSearchParams(location.search).get("wizard") === "1" || project.wizard;
    if (!wiz) return;
    setSelectedFileIds((prev) => {
      if (prev.length) return prev;
      const counter = project.files.find((f) => (f.original_filename || "").toLowerCase() === "counter.sv");
      return counter ? [counter.id] : prev;
    });
  }, [project, location.search]);

  const pendingHandoffRef = useRef(null);

  // Handoff from Coverage closure loop: prompt + optional auto-generate / open regression
  useEffect(() => {
    const st = location.state;
    if (!st || typeof st !== "object") return;
    if (st.module) setModule(st.module);
    if (typeof st.prompt === "string" && st.prompt) setPrompt(st.prompt);
    if (Array.isArray(st.fileIds) && st.fileIds.length) setSelectedFileIds(st.fileIds);
    if (st.autoGenerate) {
      pendingHandoffRef.current = {
        module: st.module || "coverage_holes",
        prompt: typeof st.prompt === "string" ? st.prompt : "",
        fileIds: Array.isArray(st.fileIds) ? st.fileIds : null,
      };
      setPendingAutoGenerate(true);
    }
    if (st.openRegression) {
      if (Array.isArray(st.seeds) && st.seeds.length) {
        setRegressionSeeds(st.seeds.map(String).join(","));
      }
      if (typeof st.coverage === "boolean") setRegressionCoverage(st.coverage);
      setShowRegression(true);
    }
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);

  useEffect(() => {
    if (!pendingAutoGenerate || !project || streaming) return;
    setPendingAutoGenerate(false);
    const handoff = pendingHandoffRef.current;
    pendingHandoffRef.current = null;
    toast.info("Starting coverage-hole generation from closure plan…");
    const t = setTimeout(() => {
      if (handoff) {
        generateRef.current?.({
          moduleOverride: handoff.module,
          promptOverride: handoff.prompt,
          fileIdsOverride: handoff.fileIds,
        });
      } else {
        generateRef.current?.();
      }
    }, 50);
    return () => clearTimeout(t);
  }, [pendingAutoGenerate, project, streaming]);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => {
        const p = h?.llm_providers || {};
        const o = h?.ollama || {};
        const product = p.product_model || { provider: "ollama", model: "chipsutra-vlsi:7b", label: "ChipSutra-VLSI" };
        const showCloud = p.show_cloud_models === true;
        const list = [];

        // Always lead with ChipSutra-VLSI. Prefer 7B whenever health says so.
        if (p.ollama || !h?.llm_providers) {
          const tag =
            o?.preferred_installed ||
            (String(p.ollama_model || "").includes("7b") ? p.ollama_model : null) ||
            (String(product.model || "").includes("7b") ? product.model : null) ||
            p.ollama_model ||
            product.model ||
            "chipsutra-vlsi:7b";
          const lead = String(tag).includes("7b") ? "chipsutra-vlsi:7b" : tag;
          let label = `ChipSutra-VLSI (${lead})`;
          if (p.ollama && o.ready === false) label = `ChipSutra-VLSI (${lead}) — starting…`;
          if (!p.ollama && h?.llm_providers) {
            label = `ChipSutra-VLSI (${lead}) — not on this host`;
          }
          list.push({ provider: "ollama", model: lead, label });
          if (String(lead).includes("7b")) {
            list.push({ provider: "ollama", model: "chipsutra-vlsi:3b", label: "ChipSutra-VLSI (3b fast)" });
          }
        } else {
          list.push({
            provider: product.provider || "ollama",
            model: product.model || "chipsutra-vlsi:7b",
            label: `${product.label || "ChipSutra-VLSI"} (default)`,
          });
        }

        if (showCloud && p.anthropic) {
          list.push({ provider: "anthropic", model: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5 (API key)" });
        }
        if (showCloud && p.openai) {
          list.push({ provider: "openai", model: "gpt-5.2", label: "GPT-5.2 (API key)" });
        }
        setModels(list.length ? list : DEFAULT_MODELS);
        setModelIdx(0);
      })
      .catch(() => {
        setModels(DEFAULT_MODELS);
        setModelIdx(0);
      });
  }, []);

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [output]);

  const handleUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true);
    for (const f of files) {
      const fd = new FormData();
      fd.append("file", f);
      const ext = f.name.split(".").pop().toLowerCase();
      const kind = ["v", "sv", "vhd", "vhdl"].includes(ext) ? "rtl" : ["pdf", "md", "docx", "txt"].includes(ext) ? "spec" : ext === "vcd" ? "vcd" : "misc";
      fd.append("kind", kind);
      try {
        await fetch(`${API}/projects/${pid}/files`, {
          method: "POST",
          headers: { Authorization: `Bearer ${getToken()}` },
          body: fd,
        }).then(r => r.ok ? r.json() : Promise.reject(r));
      } catch { toast.error(`Failed to upload ${f.name}`); }
    }
    setUploading(false);
    e.target.value = "";
    toast.success("Uploaded");
    load();
  };

  const removeFile = async (fid) => {
    try { await api.delete(`/projects/${pid}/files/${fid}`); load(); }
    catch { toast.error("Failed to delete file"); }
  };

  const openPreview = async (f) => {
    try {
      const { data } = await api.get(`/projects/${pid}/files/${f.id}/content`);
      setPreviewFile({ ...f, content: data.content });
    } catch { toast.error("Cannot open file"); }
  };

  const toggleFile = (fid) => {
    setSelectedFileIds((prev) => prev.includes(fid) ? prev.filter(x => x !== fid) : [...prev, fid]);
  };

  const generate = async (overrides = {}) => {
    if (streaming) return;
    setOutput("");
    setCurrentGenId(null);
    setLearningInfo(null);
    setStreamStatus("");
    setStreaming(true);
    const m = models[modelIdx] || DEFAULT_MODELS[0];
    const moduleToUse = overrides.moduleOverride || module;
    const promptToUse = overrides.promptOverride != null ? overrides.promptOverride : prompt;
    let fileIdsToUse = overrides.fileIdsOverride || selectedFileIds;
    if (overrides.moduleOverride) setModule(overrides.moduleOverride);
    if (overrides.promptOverride != null) setPrompt(overrides.promptOverride);
    if (overrides.fileIdsOverride) setSelectedFileIds(overrides.fileIdsOverride);

    const knownIds = new Set((project?.files || []).map((f) => f.id));
    fileIdsToUse = (fileIdsToUse || []).filter((id) => knownIds.has(id));

    const rtlFiles = (project?.files || []).filter((f) =>
      /\.(v|sv|vh|svh)$/i.test(f.original_filename || f.filename || ""),
    );

    // Testbench must have RTL selected — otherwise the LLM invents fake ports (e.g. data_in).
    if (moduleToUse === "testbench" && fileIdsToUse.length === 0) {
      if (rtlFiles.length) {
        fileIdsToUse = [rtlFiles[0].id];
        setSelectedFileIds(fileIdsToUse);
        toast.info(`Auto-selected RTL: ${rtlFiles[0].original_filename || rtlFiles[0].filename}`);
      } else {
        toast.error("Upload and select an RTL file (.v/.sv) before generating a testbench");
        setStreaming(false);
        return;
      }
    } else if (moduleToUse === "testbench" && fileIdsToUse.length) {
      setSelectedFileIds(fileIdsToUse);
    }

    try {
      let dvConfig;
      if (moduleToUse === "testbench") {
        const raw = (dvConfigText || "").trim();
        if (raw) {
          try {
            dvConfig = JSON.parse(raw);
          } catch {
            toast.error("DV config JSON is invalid — fix it or clear the box");
            setStreaming(false);
            return;
          }
        } else {
          dvConfig = {};
        }
        if (enableRal) dvConfig.enable_ral = true;
        if (!enableRal && dvConfig.enable_ral == null) dvConfig.enable_ral = false;
        if (dvScale && dvScale !== "block" && dvConfig.scale == null) dvConfig.scale = dvScale;
        if (!Object.keys(dvConfig).length) dvConfig = undefined;
      }
      const meth = moduleToUse === "testbench" ? tbMethodology : "sv";
      const modeForReq =
        moduleToUse === "testbench"
          ? meth === "sv"
            ? genMode === "smoke" || genMode === "skeleton" || genMode === "fast"
              ? "smoke"
              : "llm"
            : "llm"
          : "llm";
      const res = await fetch(`${API}/generate/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({
          project_id: pid,
          module: moduleToUse,
          model_provider: m.provider,
          model_name: m.model,
          prompt: promptToUse,
          file_ids: fileIdsToUse,
          language: project?.language || "systemverilog",
          gen_mode: modeForReq,
          tb_methodology: meth,
          ...(dvConfig ? { dv_config: dvConfig } : {}),
          ...(toolLog.trim()
            ? { tool_log: toolLog.trim(), prior_output: output || undefined }
            : {}),
        }),
      });
      if (!res.ok) {
        let detail = "Stream failed";
        try {
          const errBody = await res.json();
          detail = errBody.detail || detail;
        } catch {}
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      if (!res.body) throw new Error("Stream failed");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let engineUsed = null;
      let methFromMeta = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const p of parts) {
          const line = p.trim();
          if (!line.startsWith("data:")) continue;
          try {
            const j = JSON.parse(line.slice(5).trim());
            if (j.type === "meta") {
              setCurrentGenId(j.generation_id);
              if (j.engine) engineUsed = j.engine;
              if (j.tb_methodology) methFromMeta = j.tb_methodology;
              if (j.engine === "skeleton" && j.tb_methodology && j.tb_methodology !== "sv") {
                toast.error(
                  `Bug: asked for ${String(j.tb_methodology).toUpperCase()} but got Fast-random SV — restart API and retry.`,
                );
              }
            } else if (j.type === "progress") {
              if (j.message) setStreamStatus(j.message);
            } else if (j.type === "replace") {
              setOutput(j.content || "");
              if (j.engine) engineUsed = j.engine;
            } else if (j.type === "delta") setOutput((prev) => prev + j.content);
            else if (j.type === "error") { toast.error(j.error); }
            else if (j.type === "done") {
              if (j.engine) engineUsed = j.engine;
              if (j.learning) setLearningInfo(j.learning);
              setStreamStatus("");
              const methNote =
                methFromMeta && methFromMeta !== "sv"
                  ? ` · ${String(methFromMeta).toUpperCase()}`
                  : "";
              const verifyNote =
                j.learning?.verify_ok === true
                  ? " · Verilator OK"
                  : j.learning?.verify_skipped
                    ? ""
                    : j.learning?.verify_ok === false
                      ? " · Verilator issues"
                      : "";
              const simNote =
                j.learning?.sim_pass === true
                  ? " · sim PASS"
                  : j.learning?.sim_pass === false
                    ? " · sim FAIL"
                    : "";
              const mutNote =
                j.learning?.mutation?.kill_rate != null
                  ? ` · kill ${j.learning.mutation.kill_rate}`
                  : "";
              if (j.saved_file?.name) {
                toast.success(`Saved ${j.saved_file.name} to Files`);
                if (j.saved_file.id) {
                  setSelectedFileIds((prev) =>
                    prev.includes(j.saved_file.id) ? prev : [...prev, j.saved_file.id],
                  );
                }
              }
              toast.success(
                `LLM generation complete${methNote}${verifyNote}${simNote}${mutNote}`,
              );
              // Refresh KG learning score after each TB generation
              if (moduleToUse === "testbench") {
                api.get(`/kg/learning-score`, { params: { project_id: pid, limit: 40 } })
                  .then(({ data }) => setKgScore(data))
                  .catch(() => {});
              }
            }
          } catch {}
        }
      }
    } catch (e) {
      toast.error(e?.message || "Generation failed");
    } finally {
      setStreaming(false);
      setStreamStatus("");
      load();
    }
  };
  generateRef.current = generate;

  const rateGeneration = async (rating) => {
    if (!currentGenId || ratingBusy) return;
    setRatingBusy(true);
    try {
      const { data } = await api.post(`/generations/${currentGenId}/feedback`, { rating });
      setLearningInfo(data.learning || null);
      toast.success(rating > 0 ? "Thanks — marked helpful" : "Thanks — we'll improve from this");
      const { data: score } = await api.get(`/kg/learning-score`, { params: { project_id: pid, limit: 40 } });
      setKgScore(score);
    } catch {
      toast.error("Could not save feedback");
    }
    setRatingBusy(false);
  };

  useEffect(() => {
    if (!pid) return;
    api.get(`/kg/learning-score`, { params: { project_id: pid, limit: 40 } })
      .then(({ data }) => setKgScore(data))
      .catch(() => {});
  }, [pid]);

  const downloadOutput = () => {
    const ext = ["testbench", "assertions", "checkers", "covergroups", "spec2rtl", "coverage_holes"].includes(module) ? "sv" : "md";
    const blob = new Blob([output], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chipsutra_${module}_${Date.now()}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadZip = (data, filename) => {
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadDvPack = async () => {
    setPackBusy(true);
    try {
      const { data } = await api.post(
        "/generate/pack",
        { project_id: pid, file_ids: selectedFileIds, tb_methodology: tbMethodology },
        { responseType: "blob" },
      );
      downloadZip(data, `chipsutra_dv_pack_${Date.now()}.zip`);
      toast.success("DV pack downloaded (TB + SVA + covergroup + testplan)");
    } catch {
      toast.error("Could not build DV pack — select RTL first");
    }
    setPackBusy(false);
  };

  const downloadEvidence = async () => {
    if (!currentGenId) return;
    try {
      const { data } = await api.get(`/generations/${currentGenId}/evidence`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `chipsutra_evidence_${currentGenId.slice(0, 8)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Could not download evidence pack");
    }
  };

  const outputExt = ["testbench", "assertions", "checkers", "covergroups", "spec2rtl", "coverage_holes"].includes(module) ? "systemverilog" : "markdown";

  const wizard = new URLSearchParams(location.search).get("wizard") === "1" || project?.wizard;

  if (!project) return <div className="p-8 font-mono text-sm text-slate-400">Loading...</div>;

  return (
    <div className="p-6 max-w-[1600px]" data-testid="project-detail">
      <Link to="/app/projects" className="font-mono text-xs text-slate-400 hover:text-emerald-400 inline-flex items-center gap-1 mb-4"><ArrowLeft size={12} /> Projects</Link>
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="pin-badge uppercase">{project.design_type}</span>
            <span className="pin-badge uppercase text-emerald-400 border-emerald-500/40">{project.language}</span>
            {!project.is_owner && <span className="pin-badge uppercase text-amber-400 border-amber-500/40">shared</span>}
          </div>
          <h1 className="font-display text-3xl font-bold">{project.name}</h1>
          <p className="font-mono text-xs text-slate-400 mt-1">{project.description || "—"}</p>
          {wizard && (
            <div className="mt-3 border border-emerald-500/40 bg-emerald-500/5 p-3 font-mono text-[11px] text-slate-300" data-testid="wizard-steps">
              <div className="text-emerald-400 uppercase tracking-widest text-[10px] mb-1">60-second wizard</div>
              <ol className="list-decimal ml-4 space-y-0.5">
                <li>Select <span className="text-emerald-400">counter.sv</span> in Files</li>
                <li>Keep module = Testbench (Pure SV) and hit Generate</li>
                <li>Click Simulate — Verilator PASS is the bar (not UVM sign-off)</li>
              </ol>
            </div>
          )}
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button onClick={() => setShowFormal(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-formal"><Shield size={12} /> Formal</button>
          <button onClick={() => setShowCdc(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-cdc"><GitBranch size={12} /> CDC</button>
          <button onClick={() => setShowLab(true)} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="btn-lab"><Rocket size={12} /> Open Lab</button>
          <button onClick={() => setShowSynth(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-synth"><Cpu size={12} /> Synth</button>
          <button onClick={() => setShowSta(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-sta"><Timer size={12} /> STA</button>
          <button onClick={() => setShowRegression(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-regression"><Grid3X3 size={12} /> Regression</button>
          <button onClick={() => setShowCocotb(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-cocotb"><FlaskConical size={12} /> cocotb</button>
          <button onClick={downloadDvPack} disabled={packBusy} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-dv-pack"><Package size={12} /> {packBusy ? "Pack…" : "DV pack"}</button>
          <button onClick={() => setShowSim(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-simulate"><Play size={12} /> Simulate</button>
          <button onClick={() => setShowShare(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-share"><Users size={12} /> Share ({project.collaborators?.length || 0})</button>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* LEFT: Files */}
        <div className="col-span-12 lg:col-span-3 space-y-4">
          <div className="card-surface p-4">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Files ({project.files?.length || 0})</div>
            <label className="block">
              <input type="file" multiple accept=".v,.sv,.vhd,.vhdl,.pdf,.md,.docx,.txt,.vcd,.fst,.csv,.log,.rpt,.json,.lib,.sdc,.xml" onChange={handleUpload} className="hidden" data-testid="file-input" />
              <div className="border border-dashed border-[#1E293B] hover:border-emerald-500/50 p-4 text-center cursor-pointer transition-colors">
                <Upload size={16} className="mx-auto mb-2 text-slate-400" />
                <div className="font-mono text-xs text-slate-400">{uploading ? "Uploading..." : "Upload RTL / spec / VCD"}</div>
                <div className="font-mono text-[10px] text-slate-500 mt-1">.v .sv .vhd .pdf .md .txt .vcd</div>
              </div>
            </label>
            <div className="mt-3 space-y-1 max-h-[400px] overflow-y-auto">
              {project.files?.map((f) => (
                <div key={f.id} className={`flex items-center gap-2 p-2 border ${selectedFileIds.includes(f.id) ? 'border-emerald-500/60 bg-emerald-500/5' : 'border-transparent hover:bg-[#1A212D]'} cursor-pointer group`} onClick={() => toggleFile(f.id)} data-testid={`file-${f.id}`}>
                  <FileText size={12} className="text-slate-400 flex-shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-xs truncate">{f.original_filename}</div>
                    <div className="font-mono text-[10px] text-slate-500">{(f.size / 1024).toFixed(1)} KB · {f.kind}</div>
                  </div>
                  <button onClick={(e) => { e.stopPropagation(); openPreview(f); }} className="opacity-0 group-hover:opacity-100 text-[10px] text-emerald-400" data-testid={`file-view-${f.id}`}>view</button>
                  <button onClick={(e) => { e.stopPropagation(); removeFile(f.id); }} className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-400" data-testid={`file-del-${f.id}`}><X size={12} /></button>
                </div>
              ))}
              {(project.files?.length || 0) === 0 && <div className="font-mono text-[10px] text-slate-500 text-center py-4">No files yet</div>}
            </div>
            <GoldenDutImport projectId={pid} onImported={load} />
          </div>

          <div className="card-surface p-4">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">History ({project.generations?.length || 0})</div>
            <div className="space-y-1 max-h-[300px] overflow-y-auto">
              {project.generations?.map((g) => (
                <button key={g.id} onClick={() => { setModule(g.module); setOutput(g.output || ""); }} className="w-full text-left p-2 hover:bg-[#1A212D] font-mono text-[11px]" data-testid={`gen-${g.id}`}>
                  <div className="text-emerald-400">{g.module}</div>
                  <div className="text-slate-500 truncate">{new Date(g.created_at).toLocaleString()} · {g.model}</div>
                </button>
              ))}
              {(project.generations?.length || 0) === 0 && <div className="font-mono text-[10px] text-slate-500 text-center py-4">No runs yet</div>}
            </div>
          </div>
        </div>

        {/* MIDDLE: Module + Model + Prompt */}
        <div className="col-span-12 lg:col-span-4">
          <div className="card-surface p-4">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">AI Module</div>
            <div className="grid grid-cols-1 gap-2 max-h-[400px] overflow-y-auto pr-1">
              {MODULES.map((m) => (
                <button key={m.id} onClick={() => setModule(m.id)} className={`text-left p-3 border ${module === m.id ? 'border-emerald-500/60 bg-emerald-500/5' : 'border-[#1E293B] hover:border-slate-600'}`} data-testid={`module-${m.id}`}>
                  <div className="flex items-center gap-2">
                    <Zap size={12} className={module === m.id ? "text-emerald-400" : "text-slate-500"} />
                    <div className="font-mono text-xs font-medium">{m.label}</div>
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 mt-1 ml-5">{m.desc}</div>
                </button>
              ))}
            </div>

            <div className="mt-4 space-y-3">
              <div>
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2 flex items-center gap-2">
                  Engine
                  <span className="pin-badge text-[9px] border-emerald-500/40 text-emerald-400">AUTO</span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {models.map((m, i) => (
                    <button key={`${m.provider}-${m.model}`} onClick={() => setModelIdx(i)} className={`p-2 border text-xs font-mono ${modelIdx === i ? 'border-emerald-500/60 text-emerald-400 bg-emerald-500/5' : 'border-[#1E293B] text-slate-300'}`} data-testid={`model-${m.provider}`}>
                      {m.label}
                    </button>
                  ))}
                </div>
                <div className="font-mono text-[10px] text-slate-500 mt-1">
                  Default model: <span className="text-emerald-400/80">ChipSutra-VLSI</span> (Ollama). Claude/GPT only if the host enables cloud models.
                </div>
              </div>
              <div>
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">Prompt (optional)</div>
                {module === "testbench" && (
                  <div className="mb-2 space-y-2">
                    <div>
                      <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-1">Methodology</div>
                      <div className="grid grid-cols-4 gap-1" data-testid="tb-methodology">
                        {TB_METHODOLOGIES.map((opt) => (
                          <button
                            key={opt.id}
                            type="button"
                            title={opt.hint}
                            onClick={() => {
                              setTbMethodology(opt.id);
                              // Pure SV defaults to Class SV template; never leave Smoke stuck on.
                              setGenMode(opt.id === "sv" ? "llm" : "llm");
                            }}
                            className={`p-1.5 border text-[10px] font-mono uppercase tracking-wide ${
                              tbMethodology === opt.id
                                ? "border-emerald-500/60 text-emerald-400 bg-emerald-500/5"
                                : "border-[#1E293B] text-slate-400"
                            }`}
                            data-testid={`tb-meth-${opt.id}`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                    </div>
                    {tbMethodology === "sv" && (
                      <div>
                        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mb-1">SV style (LLM)</div>
                        <div className="grid grid-cols-2 gap-1" data-testid="tb-gen-mode">
                          {[
                            { id: "llm", label: "Class-based" },
                            { id: "smoke", label: "Procedural" },
                          ].map((opt) => (
                            <button
                              key={opt.id}
                              type="button"
                              onClick={() => setGenMode(opt.id)}
                              className={`p-1.5 border text-[10px] font-mono uppercase tracking-wide ${
                                genMode === opt.id || (opt.id === "llm" && genMode === "auto")
                                  ? "border-emerald-500/60 text-emerald-400 bg-emerald-500/5"
                                  : "border-[#1E293B] text-slate-400"
                              }`}
                              data-testid={`gen-mode-${opt.id}`}
                            >
                              {opt.label}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                <textarea
                  rows={4}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder={
                    module === "testbench"
                      ? tbMethodology === "sv"
                        ? "Always LLM. Class-based = full layered stack. Procedural = smoke-style prompt."
                        : `Generate ${tbMethodology.toUpperCase()} env/agent/test for the selected DUT (commercial simulator).`
                      : "e.g., focus on backpressure and AXI4 protocol violations"
                  }
                  className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500 resize-none"
                  data-testid="prompt-input"
                />
                {module === "testbench" && (
                  <div className="font-mono text-[10px] text-slate-500 mt-1">
                    {tbMethodology === "sv"
                      ? "All testbenches are generated by ChipSutra-VLSI (LLM). Templates are style hints only."
                      : `${tbMethodology.toUpperCase()} uses ChipSutra-VLSI (class-based). Not Verilator-gated — use a UVM/OVM/VMM-capable simulator.`}
                  </div>
                )}
                {module === "testbench" && (
                  <div className="mt-3 border border-[#1E293B] p-2">
                    <div className="flex items-center justify-between mb-1">
                      <button
                        type="button"
                        onClick={() => setShowDvConfig((v) => !v)}
                        className="font-mono text-[10px] uppercase tracking-widest text-slate-400 hover:text-emerald-400"
                        data-testid="dv-config-toggle"
                      >
                        DV config (JSON) {showDvConfig ? "▾" : "▸"}
                      </button>
                      <div className="flex items-center gap-3">
                        <label className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-slate-400">
                          <span>Scale</span>
                          <select
                            value={dvScale}
                            onChange={(e) => setDvScale(e.target.value)}
                            className="bg-[#0B0E14] border border-[#1E293B] px-1 py-0.5 text-[10px] font-mono text-slate-300"
                            data-testid="dv-scale"
                          >
                            <option value="block">block</option>
                            <option value="ip">ip</option>
                            <option value="processor">processor</option>
                            <option value="subsystem">subsystem</option>
                            <option value="soc">soc</option>
                            <option value="chiplet">chiplet</option>
                          </select>
                        </label>
                        <label className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-slate-400">
                          <input
                            type="checkbox"
                            checked={enableRal}
                            onChange={(e) => setEnableRal(e.target.checked)}
                            data-testid="enable-ral"
                          />
                          RAL (needs csr_list)
                        </label>
                      </div>
                    </div>
                    {showDvConfig && (
                      <>
                        <div className="flex justify-end mb-1">
                          <button
                            type="button"
                            className="font-mono text-[10px] uppercase tracking-widest text-emerald-400"
                            data-testid="dv-config-example"
                            onClick={async () => {
                              try {
                                const r = await api.get("/dv-config/example");
                                setDvConfigText(JSON.stringify(r.data, null, 2));
                                setEnableRal(true);
                                if (r.data?.scale) setDvScale(r.data.scale);
                              } catch {
                                toast.error("Could not load DV config example");
                              }
                            }}
                          >
                            Load example
                          </button>
                        </div>
                        <textarea
                          rows={8}
                          value={dvConfigText}
                          onChange={(e) => setDvConfigText(e.target.value)}
                          placeholder='{"scale":"ip","enable_ral":true,"csr_list":[{"name":"CTRL","addr":"0x0","access":"rw"}]}'
                          className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500 resize-y"
                          data-testid="dv-config-input"
                        />
                        <div className="font-mono text-[10px] text-slate-500 mt-1">
                          Merged with selected RTL (port names win). Same shape as CHIPSUTRA_DV_CONFIG. RAL only uses your csr_list — no invented registers.
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="font-mono text-xs uppercase tracking-widest text-slate-400">Lint / sim log (optional fix loop)</div>
                  <button
                    onClick={attachLatestToolLog}
                    disabled={attachingLog}
                    className="font-mono text-[10px] uppercase tracking-widest text-emerald-400 hover:text-emerald-300 disabled:text-slate-600"
                    data-testid="attach-tool-log-btn"
                  >
                    {attachingLog ? "Loading..." : "Attach last run"}
                  </button>
                </div>
                <textarea
                  rows={3}
                  value={toolLog}
                  onChange={(e) => setToolLog(e.target.value)}
                  placeholder="Paste Verilator / UVM / assert errors to regenerate a fix — or run Simulate (auto-attaches)"
                  className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500 resize-none"
                  data-testid="tool-log-input"
                />
                {simFindings && !simFindings.empty && (simFindings.findings || []).length > 0 && (
                  <div className="mt-2 border border-[#1E293B] bg-[#0B0E14] p-2 space-y-1" data-testid="fail-cause-panel">
                    <div className="font-mono text-[10px] uppercase tracking-widest text-amber-400">
                      Fail causes · {simFindings.summary}
                    </div>
                    {(simFindings.findings || []).slice(0, 5).map((f, i) => (
                      <div key={i} className="font-mono text-[11px] text-slate-300">
                        <span className={f.severity === "error" ? "text-red-400" : "text-amber-400"}>[{f.severity}]</span>{" "}
                        {f.title}: {f.hint}
                      </div>
                    ))}
                    <div className="flex gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => { setModule("testbench"); generate({ moduleOverride: "testbench" }); }}
                        className="font-mono text-[10px] text-emerald-400 hover:underline"
                        data-testid="apply-fail-patch"
                      >
                        Generate patch
                      </button>
                      <button
                        type="button"
                        onClick={() => setShowSim(true)}
                        className="font-mono text-[10px] text-emerald-400 hover:underline"
                        data-testid="rerun-sim"
                      >
                        Re-run Simulate
                      </button>
                    </div>
                  </div>
                )}
                <div className="font-mono text-[10px] text-slate-500 mt-1">Simulate auto-fills this field when a run finishes.</div>
              </div>
              <button onClick={generate} disabled={streaming} className="btn-neon w-full inline-flex items-center justify-center gap-2" data-testid="generate-btn">
                {streaming ? <><Loader2 size={14} className="animate-spin" /> Generating...</> : <><Cpu size={14} /> Generate ({selectedFileIds.length} files)</>}
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT: Output */}
        <div className="col-span-12 lg:col-span-5">
          <div className="card-surface flex flex-col h-[720px]">
            <div className="border-b border-[#1E293B] px-4 py-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 bg-emerald-500 rounded-full"></div>
                <div className="font-mono text-xs uppercase tracking-widest text-slate-300">Output · {module}</div>
                {streaming && (
                  <span className="font-mono text-[10px] text-emerald-400 animate-pulse" data-testid="stream-status">
                    {streamStatus || "streaming..."}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {currentGenId && output && module === "testbench" && (
                  <div className="flex items-center gap-1" data-testid="gen-feedback">
                    <button
                      type="button"
                      disabled={ratingBusy}
                      onClick={() => rateGeneration(1)}
                      className="font-mono text-[10px] px-2 py-1 border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
                      title="Helpful output"
                    >
                      + useful
                    </button>
                    <button
                      type="button"
                      disabled={ratingBusy}
                      onClick={() => rateGeneration(-1)}
                      className="font-mono text-[10px] px-2 py-1 border border-slate-600 text-slate-400 hover:bg-slate-800"
                      title="Needs improvement"
                    >
                      - weak
                    </button>
                  </div>
                )}
                {output && (
                  <button onClick={downloadOutput} className="text-xs font-mono text-emerald-400 hover:underline inline-flex items-center gap-1" data-testid="download-output">
                    <Download size={12} /> download
                  </button>
                )}
                {currentGenId && module === "testbench" && (learningInfo?.evidence || learningInfo?.sim_pass != null) && (
                  <button
                    type="button"
                    onClick={downloadEvidence}
                    className="text-xs font-mono text-emerald-400 hover:underline inline-flex items-center gap-1"
                    data-testid="download-evidence"
                  >
                    <Download size={12} /> evidence zip
                  </button>
                )}
              </div>
            </div>
            {(learningInfo || kgScore) && module === "testbench" && (
              <div className="border-b border-[#1E293B] px-4 py-2 font-mono text-[10px] text-slate-400 flex flex-wrap gap-x-4 gap-y-1" data-testid="kg-learning-bar">
                {learningInfo?.final_score != null && (
                  <span>
                    Output score: <span className="text-emerald-400">{learningInfo.final_score}</span>/100
                    {learningInfo.engine ? ` · ${learningInfo.engine}` : ""}
                    {learningInfo.verify_ok === true
                      ? " · verilator✓"
                      : learningInfo.verify_ok === false
                        ? " · verilator✗"
                        : ""}
                    {learningInfo.sim_pass === true
                      ? " · sim✓"
                      : learningInfo.sim_pass === false
                        ? " · sim✗"
                        : ""}
                    {learningInfo.mutation?.kill_rate != null
                      ? ` · kill ${learningInfo.mutation.kill_rate}`
                      : ""}
                  </span>
                )}
                {kgScore?.kg_learning_score != null && (
                  <span>
                    KG learning: <span className="text-emerald-400">{kgScore.kg_learning_score}</span>/100
                    {kgScore.grade ? ` (${kgScore.grade})` : ""}
                    {kgScore.trend ? ` · ${kgScore.trend}` : ""}
                  </span>
                )}
                {kgScore?.interpretation && (
                  <span className="text-slate-500 w-full">{kgScore.interpretation}</span>
                )}
              </div>
            )}
            <div ref={outputRef} className="flex-1 overflow-auto bg-[#0B0E14]">
              {output ? (
                <Editor
                  height="100%"
                  theme="vs-dark"
                  language={outputExt}
                  value={output}
                  options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    fontFamily: "JetBrains Mono",
                    fontSize: 12,
                    lineNumbers: "on",
                    scrollBeyondLastLine: false,
                    wordWrap: "on",
                  }}
                />
              ) : (
                <div className="p-8 font-mono text-xs text-slate-500">
                  <div className="text-emerald-400">chipsutra ~ $</div>
                  <div className="mt-2 text-slate-400">Select an AI module, choose files, and hit Generate.</div>
                  <div className="mt-1 text-slate-500 cli-caret"></div>
                </div>
              )}
            </div>
            {currentGenId && !streaming && (
              <CommentsPanel generationId={currentGenId} currentUserId={user?.id} />
            )}
          </div>
        </div>
      </div>

      {showShare && <ShareModal project={project} onClose={() => setShowShare(false)} onUpdate={load} />}
      {showSim && (
        <SimulationPanel
          project={project}
          selectedFileIds={selectedFileIds}
          tbMethodology={tbMethodology}
          generatedOutput={output}
          onClose={() => setShowSim(false)}
          onVcdCreated={load}
          onLogReady={onSimLogReady}
        />
      )}
      {showFormal && (
        <FormalPanel
          project={project}
          selectedFileIds={selectedFileIds}
          onClose={() => setShowFormal(false)}
          onSendDebug={(log) => {
            setToolLog(log || "");
            setModule("debug");
            setShowFormal(false);
            toast.success("CEX/log attached — Generate Debug next");
          }}
        />
      )}
      {showCdc && <CdcPanel project={project} selectedFileIds={selectedFileIds} onClose={() => setShowCdc(false)} />}
      {showSynth && <SynthPanel project={project} selectedFileIds={selectedFileIds} onClose={() => setShowSynth(false)} onArtifacts={load} />}
      {showRegression && (
        <RegressionPanel
          project={project}
          selectedFileIds={selectedFileIds}
          onClose={() => { setShowRegression(false); setRegressionSeeds(null); setRegressionCoverage(null); }}
          initialSeeds={regressionSeeds}
          initialCoverage={regressionCoverage}
        />
      )}
      {showCocotb && <CocotbPanel project={project} selectedFileIds={selectedFileIds} onClose={() => setShowCocotb(false)} onUpdate={load} />}
      {showSta && <StaPanel project={project} selectedFileIds={selectedFileIds} onClose={() => setShowSta(false)} />}
      {showLab && (
        <LabPipelinePanel
          project={project}
          selectedFileIds={selectedFileIds}
          onClose={() => setShowLab(false)}
          onArtifacts={load}
        />
      )}

      {/* File preview modal */}
      {previewFile && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" onClick={() => setPreviewFile(null)} data-testid="file-preview-modal">
          <div className="card-surface w-full max-w-4xl h-[80vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="border-b border-[#1E293B] px-4 py-3 flex items-center justify-between">
              <div className="font-mono text-xs">{previewFile.original_filename}</div>
              <button onClick={() => setPreviewFile(null)} className="text-slate-400 hover:text-slate-100"><X size={16} /></button>
            </div>
            <div className="flex-1 overflow-hidden">
              <Editor
                height="100%"
                theme="vs-dark"
                language={langMap[previewFile.ext] || "plaintext"}
                value={previewFile.content}
                options={{ readOnly: true, minimap: { enabled: false }, fontFamily: "JetBrains Mono", fontSize: 12 }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
