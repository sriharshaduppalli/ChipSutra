import { useEffect, useState, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { api, API, getToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import Editor from "@monaco-editor/react";
import { Upload, FileText, Cpu, Zap, Download, Loader2, X, ArrowLeft, Play, Users, Shield } from "lucide-react";
import ShareModal from "@/components/ShareModal";
import SimulationPanel from "@/components/SimulationPanel";
import CommentsPanel from "@/components/CommentsPanel";
import FormalPanel from "@/components/FormalPanel";

const MODULES = [
  { id: "testbench", label: "UVM Testbench", desc: "Scalable, reusable testbench with driver/monitor/scoreboard/sequences" },
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

const DEFAULT_MODELS = [
  { provider: "ollama", model: "chipsutra-vlsi:3b", label: "ChipSutra-VLSI (local)" },
];

const langMap = { v: "verilog", sv: "systemverilog", vhd: "vhdl", vhdl: "vhdl", md: "markdown", txt: "plaintext", log: "plaintext", rpt: "plaintext" };

export default function ProjectDetail() {
  const { pid } = useParams();
  const { user } = useAuth();
  const [project, setProject] = useState(null);
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [module, setModule] = useState("testbench");
  const [models, setModels] = useState(DEFAULT_MODELS);
  const [modelIdx, setModelIdx] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [toolLog, setToolLog] = useState("");
  const [output, setOutput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const [showShare, setShowShare] = useState(false);
  const [showSim, setShowSim] = useState(false);
  const [showFormal, setShowFormal] = useState(false);
  const [currentGenId, setCurrentGenId] = useState(null);
  const outputRef = useRef(null);

  const load = async () => {
    const { data } = await api.get(`/projects/${pid}`);
    setProject(data);
  };
  useEffect(() => { load(); }, [pid]);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => {
        if (!h?.llm_providers) return;
        const p = h.llm_providers;
        const o = h.ollama || {};
        const list = [];
        if (p.ollama) {
          const tag = p.ollama_model || "chipsutra-vlsi:3b";
          list.push({
            provider: "ollama",
            model: tag,
            label: o.ready === false
              ? `ChipSutra-VLSI (${tag}) — starting…`
              : `ChipSutra-VLSI (${tag})`,
          });
        }
        if (p.anthropic) {
          list.push({ provider: "anthropic", model: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5 (API key)" });
        }
        if (p.openai) {
          list.push({ provider: "openai", model: "gpt-5.2", label: "GPT-5.2 (API key)" });
        }
        if (list.length) {
          setModels(list);
          setModelIdx(0);
        }
      })
      .catch(() => {});
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

  const generate = async () => {
    if (streaming) return;
    setOutput("");
    setCurrentGenId(null);
    setStreaming(true);
    const m = models[modelIdx] || DEFAULT_MODELS[0];
    try {
      const res = await fetch(`${API}/generate/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({
          project_id: pid,
          module,
          model_provider: m.provider,
          model_name: m.model,
          prompt,
          file_ids: selectedFileIds,
          language: project?.language || "systemverilog",
          ...(toolLog.trim()
            ? { tool_log: toolLog.trim(), prior_output: output || undefined }
            : {}),
        }),
      });
      if (!res.ok || !res.body) throw new Error("Stream failed");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
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
            if (j.type === "meta") setCurrentGenId(j.generation_id);
            else if (j.type === "delta") setOutput((prev) => prev + j.content);
            else if (j.type === "error") { toast.error(j.error); }
            else if (j.type === "done") { toast.success("Generation complete"); }
          } catch {}
        }
      }
    } catch (e) {
      toast.error("Generation failed");
    } finally {
      setStreaming(false);
      load();
    }
  };

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

  const outputExt = ["testbench", "assertions", "checkers", "covergroups", "spec2rtl", "coverage_holes"].includes(module) ? "systemverilog" : "markdown";

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
        </div>
        <div className="flex gap-2">
          <button onClick={() => setShowFormal(true)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="btn-formal"><Shield size={12} /> Formal</button>
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
              <input type="file" multiple accept=".v,.sv,.vhd,.vhdl,.pdf,.md,.docx,.txt,.vcd,.csv,.log,.rpt,.json" onChange={handleUpload} className="hidden" data-testid="file-input" />
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
                <div className="font-mono text-[10px] text-slate-500 mt-1">Default: ChipSutra-VLSI via Ollama (no API cost). Cloud models appear only if keys are configured.</div>
              </div>
              <div>
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">Prompt (optional)</div>
                <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g., focus on backpressure and AXI4 protocol violations" className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500 resize-none" data-testid="prompt-input" />
              </div>
              <div>
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">Lint / sim log (optional fix loop)</div>
                <textarea
                  rows={3}
                  value={toolLog}
                  onChange={(e) => setToolLog(e.target.value)}
                  placeholder="Paste Verilator / UVM / assert errors to regenerate a fix (sends prior output too)"
                  className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500 resize-none"
                  data-testid="tool-log-input"
                />
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
                {streaming && <span className="font-mono text-[10px] text-emerald-400 animate-pulse">streaming...</span>}
              </div>
              {output && (
                <button onClick={downloadOutput} className="text-xs font-mono text-emerald-400 hover:underline inline-flex items-center gap-1" data-testid="download-output">
                  <Download size={12} /> download
                </button>
              )}
            </div>
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
      {showSim && <SimulationPanel project={project} selectedFileIds={selectedFileIds} onClose={() => setShowSim(false)} onVcdCreated={load} />}
      {showFormal && <FormalPanel project={project} selectedFileIds={selectedFileIds} onClose={() => setShowFormal(false)} />}

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
