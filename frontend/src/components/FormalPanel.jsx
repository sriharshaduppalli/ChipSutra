import { useState } from "react";
import { API, getToken } from "@/lib/api";
import { Shield, Loader2, X, Play, Waves } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";

export default function FormalPanel({ project, selectedFileIds, onClose }) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [engine, setEngine] = useState(null);
  const [topModule, setTopModule] = useState("");
  const [depth, setDepth] = useState(10);
  const [mode, setMode] = useState("prove");
  const [properties, setProperties] = useState([]);
  const [cexFileId, setCexFileId] = useState(null);

  const rtlIds = selectedFileIds.filter(fid => {
    const f = (project.files || []).find(x => x.id === fid);
    return f && ["v", "sv"].includes(f.ext);
  });

  const run = async () => {
    if (rtlIds.length === 0) { toast.error("Select at least one .v/.sv file"); return; }
    setLogs([]); setStatus(null); setEngine(null); setProperties([]); setCexFileId(null); setRunning(true);
    try {
      const res = await fetch(`${API}/formal/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          rtl_file_ids: rtlIds,
          top_module: topModule || null,
          depth,
          mode,
        }),
      });
      if (!res.ok || !res.body) throw new Error();
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
            else if (j.type === "properties") setProperties(j.items || []);
            else if (j.type === "cex") setCexFileId(j.file_id);
            else if (j.type === "done") setStatus(j.status);
          } catch {}
        }
      }
    } catch { toast.error("Formal run failed"); }
    setRunning(false);
  };

  const colorFor = (lvl) => lvl === "error" ? "text-red-400" : lvl === "warn" ? "text-amber-400" : lvl === "success" ? "text-emerald-400" : "text-slate-300";

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" data-testid="formal-modal">
      <div className="card-surface w-full max-w-4xl h-[85vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-emerald-400" />
            <div className="font-mono text-sm">Formal Verification (SymbiYosys) · {project.name}</div>
            {engine && <span className={`pin-badge ${engine === 'mock' ? 'text-amber-400 border-amber-500/40' : 'text-emerald-400 border-emerald-500/40'}`}>{engine}</span>}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100" data-testid="formal-close"><X size={16} /></button>
        </div>
        <div className="p-4 border-b border-[#1E293B] flex flex-wrap items-center gap-3">
          <select value={mode} onChange={e => setMode(e.target.value)} className="bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="formal-mode">
            <option value="prove">prove (BMC + induction)</option>
            <option value="bmc">bmc (bounded)</option>
          </select>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-slate-400">DEPTH</span>
            <input type="number" min={1} max={30} value={depth} onChange={e => setDepth(parseInt(e.target.value) || 10)} className="w-16 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="formal-depth" />
          </div>
          <input placeholder="top module (auto)" value={topModule} onChange={e => setTopModule(e.target.value)} className="flex-1 min-w-[180px] bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="formal-top" />
          <button disabled={running || rtlIds.length === 0} onClick={run} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="formal-run">
            {running ? <><Loader2 size={12} className="animate-spin" /> Proving...</> : <><Play size={12} /> Run Formal</>}
          </button>
        </div>
        <div className="p-2 border-b border-[#1E293B] font-mono text-[10px] text-slate-500">RTL must contain <span className="text-emerald-400">`assert property`</span>, <span className="text-emerald-400">`assume property`</span>, or <span className="text-emerald-400">`cover property`</span>. Use the AI module "Formal Hints" to draft them.</div>
        {properties.length > 0 && (
          <div className="px-4 py-2 border-b border-[#1E293B] max-h-28 overflow-auto">
            <div className="font-mono text-[10px] text-slate-400 mb-1">PROPERTY TABLE</div>
            {properties.map((p, i) => (
              <div key={i} className={`font-mono text-[11px] ${p.status === "PASS" ? "text-emerald-400" : p.status === "FAIL" ? "text-red-400" : "text-slate-300"}`}>
                [{p.status}] {p.name}
              </div>
            ))}
          </div>
        )}
        <div className="flex-1 overflow-auto bg-[#0B0E14] p-4 font-mono text-[11px] scanline">
          {logs.length === 0 && !running && (
            <div className="text-slate-500">
              <div className="text-emerald-400">chipsutra ~ formal $</div>
              <div className="mt-2">Select .v/.sv files with SVA properties and hit Run Formal.</div>
              <div className="mt-1">Runs <span className="text-emerald-400">SymbiYosys</span> with <span className="text-emerald-400">Yosys + Z3 SMT</span>.</div>
            </div>
          )}
          {logs.map((l, i) => (<div key={i} className={colorFor(l.level)}>{l.line}</div>))}
          {running && <div className="text-emerald-400 mt-2 cli-caret"></div>}
          {status && (
            <div className={`mt-4 p-2 border-l-2 ${status === 'done' ? 'border-emerald-500 text-emerald-400' : 'border-red-500 text-red-400'}`}>
              [{status.toUpperCase()}] Formal {status === 'done' ? 'proof completed' : 'ended with counterexamples'}
              {cexFileId && (
                <div className="mt-2 text-amber-400 flex items-center gap-1">
                  <Waves size={12} /> CEX VCD saved. <Link to="/app/waveform" className="underline">Open Waveform →</Link>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
