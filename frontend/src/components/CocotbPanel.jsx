import { useState } from "react";
import { API, api, getToken } from "@/lib/api";
import { FlaskConical, Loader2, X, Play, FilePlus } from "lucide-react";
import { toast } from "sonner";

export default function CocotbPanel({ project, selectedFileIds, onClose, onUpdate }) {
  const [running, setRunning] = useState(false);
  const [scaffolding, setScaffolding] = useState(false);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState(null);
  const [topModule, setTopModule] = useState("");

  const rtl = (project.files || []).find((f) => selectedFileIds.includes(f.id) && ["v", "sv"].includes((f.ext || "").toLowerCase()))
    || (project.files || []).find((f) => ["v", "sv"].includes((f.ext || "").toLowerCase()));

  const hasScaffold = (project.files || []).some((f) => (f.original_filename || "").toLowerCase() === "makefile")
    && (project.files || []).some((f) => /^test_.*\.py$/i.test(f.original_filename || ""));

  const scaffold = async () => {
    if (!rtl) return toast.error("Select or upload an RTL file first");
    setScaffolding(true);
    try {
      await api.post(`/projects/${project.id}/scaffold/cocotb`, {
        rtl_file_id: rtl.id,
        top_module: topModule || null,
      });
      toast.success("cocotb Makefile + Python smoke test added");
      if (onUpdate) onUpdate();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not scaffold cocotb");
    }
    setScaffolding(false);
  };

  const run = async () => {
    setRunning(true); setLogs([]); setStatus(null); setStats(null);
    try {
      const res = await fetch(`${API}/cocotb/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          top_module: topModule || null,
          sim: "verilator",
        }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "cocotb stream failed");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          try {
            const event = JSON.parse(line.slice(5).trim());
            if (event.type === "log") setLogs((prev) => [...prev, event]);
            else if (event.type === "done") {
              setStatus(event.status);
              setStats(event.stats || null);
            }
          } catch {}
        }
      }
    } catch (e) {
      toast.error(e.message || "cocotb run failed");
    }
    setRunning(false);
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" data-testid="cocotb-modal">
      <div className="card-surface w-full max-w-4xl h-[82vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical size={16} className="text-emerald-400" />
            <span className="font-mono text-sm">cocotb · {project.name}</span>
            <span className="pin-badge text-amber-400 border-amber-500/40">experimental</span>
          </div>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        <div className="p-4 border-b border-[#1E293B] flex flex-wrap gap-3 items-center">
          <input
            value={topModule}
            onChange={(e) => setTopModule(e.target.value)}
            placeholder="top module (auto)"
            className="flex-1 min-w-[10rem] bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono"
          />
          <button onClick={scaffold} disabled={scaffolding || !rtl} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="cocotb-scaffold">
            {scaffolding ? <Loader2 size={12} className="animate-spin" /> : <FilePlus size={12} />} Scaffold
          </button>
          <button onClick={run} disabled={running} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="cocotb-run">
            {running ? <><Loader2 size={12} className="animate-spin" /> Running</> : <><Play size={12} /> Run make SIM=verilator</>}
          </button>
        </div>
        <div className="px-4 py-2 border-b border-[#1E293B] font-mono text-[10px] text-slate-500">
          {hasScaffold
            ? "Makefile + test_*.py detected — run streams make logs and persists cocotb_runs."
            : "Scaffold first to add Makefile + test_*.py, then run. Missing cocotb/make/verilator returns a mock with actionable errors."}
          {stats && <span className="text-emerald-400 ml-2">hints pass={stats.passed_hints} fail={stats.failed_hints}</span>}
        </div>
        <div className="flex-1 overflow-auto bg-[#0B0E14] p-4 font-mono text-[11px]">
          {logs.map((l, i) => (
            <div key={i} className={l.level === "error" ? "text-red-400" : l.level === "warn" ? "text-amber-400" : "text-slate-300"}>{l.line}</div>
          ))}
          {!logs.length && !running && (
            <div className="text-slate-500">One-click cocotb runner uses project RTL + scaffold. Requires cocotb-config, make, and Verilator on PATH for a real run.</div>
          )}
          {status && <div className={`mt-4 ${status === "done" ? "text-emerald-400" : status === "mock" ? "text-amber-400" : "text-red-400"}`}>[{status.toUpperCase()}]</div>}
        </div>
      </div>
    </div>
  );
}
