import { useState } from "react";
import { API, getToken } from "@/lib/api";
import { Cpu, Loader2, X, Play } from "lucide-react";
import { toast } from "sonner";

export default function SynthPanel({ project, selectedFileIds, onClose }) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState(null);
  const [mode, setMode] = useState("synth");
  const [topModule, setTopModule] = useState("");

  const selected = selectedFileIds.filter((fid) => {
    const f = (project.files || []).find((x) => x.id === fid);
    return f && ["v", "sv"].includes((f.ext || "").toLowerCase());
  });
  const rtlIds = selected.length
    ? selected
    : (project.files || []).filter((f) => ["v", "sv"].includes((f.ext || "").toLowerCase())).map((f) => f.id);

  const run = async () => {
    if (!rtlIds.length) return toast.error("Select or upload synthesizable RTL");
    setRunning(true); setLogs([]); setStats(null); setStatus(null);
    try {
      const res = await fetch(`${API}/synth/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          rtl_file_ids: rtlIds,
          top_module: topModule || null,
          mode,
        }),
      });
      if (!res.ok || !res.body) throw new Error("Synthesis stream failed");
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
            else if (event.type === "stats") setStats(event.stats);
            else if (event.type === "done") setStatus(event.status);
          } catch {}
        }
      }
    } catch (e) {
      toast.error(e.message || "Synthesis failed");
    }
    setRunning(false);
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6">
      <div className="card-surface w-full max-w-4xl h-[82vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2"><Cpu size={16} className="text-emerald-400" /><span className="font-mono text-sm">Yosys Synthesis / Equivalence · {project.name}</span></div>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        <div className="p-4 border-b border-[#1E293B] flex gap-3">
          <select value={mode} onChange={(e) => setMode(e.target.value)} className="bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono">
            <option value="synth">synthesis sanity</option>
            <option value="equiv">pre/post optimization equivalence</option>
          </select>
          <input value={topModule} onChange={(e) => setTopModule(e.target.value)} placeholder="top module (auto)" className="flex-1 bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono" />
          <button onClick={run} disabled={running || !rtlIds.length} className="btn-neon text-xs inline-flex items-center gap-1">
            {running ? <><Loader2 size={12} className="animate-spin" /> Running</> : <><Play size={12} /> Run</>}
          </button>
        </div>
        {stats && (
          <div className="px-4 py-2 border-b border-[#1E293B] font-mono text-xs text-emerald-400">
            cells={stats.cells ?? "—"} · wires={stats.wires ?? "—"} · memories={stats.memories ?? "—"} · equivalence={stats.equivalence ?? "n/a"}
          </div>
        )}
        <div className="flex-1 overflow-auto bg-[#0B0E14] p-4 font-mono text-[11px]">
          {logs.map((l, i) => <div key={i} className={l.level === "error" ? "text-red-400" : "text-slate-300"}>{l.line}</div>)}
          {!logs.length && !running && <div className="text-slate-500">Run Yosys to verify that generated RTL elaborates and synthesizes.</div>}
          {status && <div className={`mt-4 ${status === "done" ? "text-emerald-400" : "text-red-400"}`}>[{status.toUpperCase()}]</div>}
        </div>
      </div>
    </div>
  );
}
