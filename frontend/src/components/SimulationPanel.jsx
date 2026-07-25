import { useState, useEffect, useMemo } from "react";
import { API, getToken } from "@/lib/api";
import { Play, Loader2, X, Terminal, Waves, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";

function rtlFileIds(project) {
  return (project.files || [])
    .filter((f) => ["v", "sv"].includes((f.ext || "").toLowerCase()))
    .map((f) => f.id);
}

export default function SimulationPanel({ project, selectedFileIds, onClose, onVcdCreated }) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [topModule, setTopModule] = useState("");
  const [status, setStatus] = useState(null);
  const [engine, setEngine] = useState(null);
  const [mode, setMode] = useState("lint");
  const [simTime, setSimTime] = useState(1000);
  const [vcdFileId, setVcdFileId] = useState(null);
  const [verilatorAvailable, setVerilatorAvailable] = useState(null);
  const [includeAllRtl, setIncludeAllRtl] = useState(false);

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => setVerilatorAvailable(h?.verilator === true))
      .catch(() => setVerilatorAvailable(null));
  }, []);

  const selectedRtlIds = selectedFileIds.filter((fid) => {
    const f = (project.files || []).find((x) => x.id === fid);
    return f && ["v", "sv"].includes((f.ext || "").toLowerCase());
  });

  const allRtlIds = useMemo(() => rtlFileIds(project), [project]);
  const rtlIds = includeAllRtl ? allRtlIds : selectedRtlIds;

  useEffect(() => {
    if (selectedRtlIds.length === 0 && allRtlIds.length > 0) {
      setIncludeAllRtl(true);
    }
  }, [project.id, selectedRtlIds.length, allRtlIds.length]);

  const tbFile = (project.files || []).find(
    (f) => selectedFileIds.includes(f.id) && f.kind === "tb",
  );

  const run = async () => {
    if (rtlIds.length === 0) {
      toast.error("Select at least one .v/.sv file in the Files list (left), or use Select all RTL.");
      return;
    }
    setLogs([]); setStatus(null); setEngine(null); setVcdFileId(null); setRunning(true);
    try {
      const res = await fetch(`${API}/simulate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          rtl_file_ids: rtlIds,
          tb_file_id: tbFile?.id,
          top_module: topModule || null,
          mode,
          sim_time_ns: simTime,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      if (!res.body) throw new Error("No response stream");
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
            if (j.type === "meta") setEngine(j.engine);
            else if (j.type === "log") setLogs(prev => [...prev, { level: j.level || "info", line: j.line }]);
            else if (j.type === "done") { setStatus(j.status); if (j.vcd_file_id) { setVcdFileId(j.vcd_file_id); onVcdCreated && onVcdCreated(); } }
          } catch {}
        }
      }
    } catch (e) {
      toast.error(e.message || "Simulation failed");
    }
    setRunning(false);
  };

  const colorFor = (lvl) => lvl === "error" ? "text-red-400" : lvl === "warn" ? "text-amber-400" : lvl === "success" ? "text-emerald-400" : "text-slate-300";

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" data-testid="sim-modal">
      <div className="card-surface w-full max-w-4xl h-[85vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal size={16} className="text-emerald-400" />
            <div className="font-mono text-sm">Verilator Simulation · {project.name}</div>
            {engine && <span className={`pin-badge ${engine === 'mock' ? 'text-amber-400 border-amber-500/40' : 'text-emerald-400 border-emerald-500/40'}`}>{engine}</span>}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100" data-testid="sim-close"><X size={16} /></button>
        </div>
        {verilatorAvailable === false && (
          <div className="mx-4 mt-3 p-3 border border-amber-500/40 bg-amber-500/5 font-mono text-[11px] text-amber-200 flex gap-2 items-start">
            <AlertTriangle size={14} className="flex-shrink-0 mt-0.5 text-amber-400" />
            <div>
              <div className="text-amber-400 font-medium">Verilator not found on this backend</div>
              <div className="text-slate-400 mt-1">
                Native Windows setup runs <span className="text-amber-300">mock</span> sim only (demo logs, no real compile).
                For real Lint / Compile+Run use the Docker backend (includes Verilator) or WSL2:{" "}
                <span className="text-slate-300">sudo apt install verilator</span>.
              </div>
            </div>
          </div>
        )}
        {rtlIds.length === 0 && allRtlIds.length > 0 && !includeAllRtl && (
          <div className="mx-4 mt-3 p-3 border border-emerald-500/40 bg-emerald-500/5 font-mono text-[11px] text-slate-300">
            No RTL files selected. In the project page, click your <span className="text-emerald-400">.v / .sv</span> files in the
            left <span className="text-emerald-400">Files</span> panel (green highlight), or{" "}
            <button
              type="button"
              className="text-emerald-400 underline"
              onClick={() => setIncludeAllRtl(true)}
            >
              use all {allRtlIds.length} RTL file(s) in this project
            </button>
            .
          </div>
        )}
        {allRtlIds.length === 0 && (
          <div className="mx-4 mt-3 p-3 border border-red-500/40 bg-red-500/5 font-mono text-[11px] text-slate-300">
            Upload at least one <span className="text-red-400">.v</span> or <span className="text-red-400">.sv</span> RTL file.
            Generated testbench text in the output pane must be downloaded and re-uploaded as a file before sim.
          </div>
        )}
        <div className="p-4 border-b border-[#1E293B] flex flex-wrap items-center gap-3">
          <div className="flex border border-[#1E293B]">
            <button onClick={() => setMode("lint")} className={`px-3 py-1.5 text-xs font-mono ${mode === "lint" ? 'bg-emerald-500/10 text-emerald-400' : 'text-slate-400'}`} data-testid="sim-mode-lint">Lint</button>
            <button onClick={() => setMode("run")} className={`px-3 py-1.5 text-xs font-mono ${mode === "run" ? 'bg-emerald-500/10 text-emerald-400' : 'text-slate-400'}`} data-testid="sim-mode-run">Compile + Run</button>
          </div>
          {mode === "run" && (
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-slate-400">SIM TIME</span>
              <input type="number" min={50} max={100000} value={simTime} onChange={e => setSimTime(parseInt(e.target.value) || 1000)} className="w-24 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="sim-time" />
              <span className="font-mono text-[10px] text-slate-500">cycles</span>
            </div>
          )}
          <input placeholder="top module (auto)" value={topModule} onChange={e => setTopModule(e.target.value)} className="flex-1 min-w-[180px] bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="sim-top" />
          <button disabled={running || rtlIds.length === 0} onClick={run} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="sim-run">
            {running ? <><Loader2 size={12} className="animate-spin" /> Running...</> : <><Play size={12} /> Run</>}
          </button>
        </div>
        <div className="p-2 border-b border-[#1E293B] font-mono text-[10px] text-slate-500">
          Selected: <span className="text-emerald-400">{rtlIds.length}</span> RTL
          {includeAllRtl && selectedRtlIds.length === 0 && (
            <span className="text-amber-400"> (all project RTL)</span>
          )}
          · TB: <span className="text-emerald-400">{tbFile?.original_filename || "auto-detect"}</span>
          {mode === "run" && <span> · Runs verilator --cc --build + captures VCD if TB has $dumpvars.</span>}
        </div>
        <div className="flex-1 overflow-auto bg-[#0B0E14] p-4 font-mono text-[11px] scanline">
          {logs.length === 0 && !running && (
            <div className="text-slate-500">
              <div className="text-emerald-400">chipsutra ~ sim $</div>
              <div className="mt-2">Pick <span className="text-emerald-400">Lint</span> for fast static checks, or <span className="text-emerald-400">Compile + Run</span> to actually simulate and capture a VCD.</div>
            </div>
          )}
          {logs.map((l, i) => (<div key={i} className={colorFor(l.level)}>{l.line}</div>))}
          {running && <div className="text-emerald-400 mt-2 cli-caret"></div>}
          {status && (
            <div className={`mt-4 p-2 border-l-2 ${status === 'done' ? 'border-emerald-500 text-emerald-400' : 'border-red-500 text-red-400'}`}>
              [{status.toUpperCase()}] {status === 'done' ? 'Simulation completed successfully' : 'Simulation ended with errors'}
              {vcdFileId && <div className="mt-2 text-emerald-400 flex items-center gap-1"><Waves size={12} /> VCD captured. <Link to="/app/waveform" className="underline">Open Waveform viewer →</Link></div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
