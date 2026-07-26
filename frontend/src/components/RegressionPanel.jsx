import { useCallback, useEffect, useMemo, useState } from "react";
import { API, api, getToken } from "@/lib/api";
import { Grid3X3, Loader2, Play, X } from "lucide-react";
import { toast } from "sonner";

export default function RegressionPanel({ project, selectedFileIds, onClose }) {
  const [running, setRunning] = useState(false);
  const [seeds, setSeeds] = useState("1,2,3");
  const [maxWorkers, setMaxWorkers] = useState(1);
  const [coverage, setCoverage] = useState(false);
  const [results, setResults] = useState([]);
  const [summary, setSummary] = useState(null);
  const [trends, setTrends] = useState(null);
  const [covTrends, setCovTrends] = useState(null);

  const rtlIds = useMemo(() => {
    const selected = selectedFileIds.filter((fid) => {
      const f = (project.files || []).find((x) => x.id === fid);
      return f && ["v", "sv"].includes((f.ext || "").toLowerCase());
    });
    return selected.length
      ? selected
      : (project.files || []).filter((f) => ["v", "sv"].includes((f.ext || "").toLowerCase())).map((f) => f.id);
  }, [project.files, selectedFileIds]);

  const testbenches = useMemo(
    () => (project.files || []).filter(
      (f) => ["v", "sv"].includes((f.ext || "").toLowerCase())
        && (f.kind === "tb" || /(^|[_-])(tb|test)/i.test(f.original_filename || "")),
    ),
    [project.files],
  );

  const loadTrends = useCallback(async () => {
    try {
      const [reg, cov] = await Promise.all([
        api.get(`/projects/${project.id}/regressions/trends`),
        api.get(`/projects/${project.id}/coverage/trends`),
      ]);
      setTrends(reg.data);
      setCovTrends(cov.data);
    } catch {
      /* trends are optional */
    }
  }, [project.id]);

  useEffect(() => { loadTrends(); }, [loadTrends]);

  const run = async () => {
    if (!rtlIds.length) return toast.error("No RTL files available");
    const parsedSeeds = seeds.split(",").map((s) => parseInt(s.trim(), 10)).filter(Number.isFinite);
    const workers = Math.max(1, Math.min(4, Number(maxWorkers) || 1));
    const cases = (testbenches.length ? testbenches : [{ id: null, original_filename: "default" }]).map((tb) => ({
      name: tb.original_filename,
      rtl_file_ids: rtlIds.filter((id) => id !== tb.id),
      tb_file_id: tb.id,
      mode: "run",
      seeds: parsedSeeds.length ? parsedSeeds : [1],
      coverage: !!coverage,
    }));
    if (cases.length * (parsedSeeds.length || 1) > 20) return toast.error("Matrix exceeds 20 runs");
    setRunning(true); setResults([]); setSummary(null);
    try {
      const res = await fetch(`${API}/regress/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          cases,
          stop_on_fail: false,
          max_workers: workers,
        }),
      });
      if (!res.ok || !res.body) throw new Error("Regression stream failed");
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
          if (!part.trim().startsWith("data:")) continue;
          try {
            const event = JSON.parse(part.trim().slice(5).trim());
            if (event.type === "case_start") setResults((prev) => {
              const exists = prev.find((r) => r.index === event.index);
              return exists ? prev.map((r) => (r.index === event.index ? event : r)) : [...prev, event];
            });
            else if (event.type === "case_done") setResults((prev) => {
              const exists = prev.find((r) => r.index === event.index);
              return exists ? prev.map((r) => (r.index === event.index ? event : r)) : [...prev, event];
            });
            else if (event.type === "done") setSummary(event);
          } catch {}
        }
      }
      loadTrends();
    } catch (e) {
      toast.error(e.message || "Regression failed");
    }
    setRunning(false);
  };

  const latest = trends?.points?.length ? trends.points[trends.points.length - 1] : null;
  const covLatest = covTrends?.latest;

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6">
      <div className="card-surface w-full max-w-4xl h-[80vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex gap-2 items-center"><Grid3X3 size={16} className="text-emerald-400" /><span className="font-mono text-sm">Regression Matrix · {project.name}</span></div>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        <div className="p-4 border-b border-[#1E293B] flex flex-wrap gap-3 items-center">
          <span className="font-mono text-[10px] text-slate-400">SEEDS</span>
          <input value={seeds} onChange={(e) => setSeeds(e.target.value)} className="w-40 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono" placeholder="1,2,3" />
          <span className="font-mono text-[10px] text-slate-400">WORKERS</span>
          <select value={maxWorkers} onChange={(e) => setMaxWorkers(Number(e.target.value))} className="bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono">
            {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <label className="font-mono text-[10px] text-slate-400 inline-flex items-center gap-1">
            <input type="checkbox" checked={coverage} onChange={(e) => setCoverage(e.target.checked)} />
            coverage
          </label>
          <span className="font-mono text-[10px] text-slate-500 flex-1">{testbenches.length || 1} test(s) × seeds; max 20 · workers 1–4</span>
          <button onClick={run} disabled={running} className="btn-neon text-xs inline-flex items-center gap-1">
            {running ? <><Loader2 size={12} className="animate-spin" /> Running</> : <><Play size={12} /> Run Matrix</>}
          </button>
        </div>
        {(latest || covLatest != null) && (
          <div className="px-4 py-2 font-mono text-[10px] border-b border-[#1E293B] text-slate-400 flex flex-wrap gap-4">
            {latest && <span>history: last pass={latest.passed} fail={latest.failed} · {trends?.count || 0} runs</span>}
            {covLatest != null && <span>coverage trend: latest={covLatest}%{covTrends?.delta_vs_oldest != null ? ` · Δ=${covTrends.delta_vs_oldest}` : ""}</span>}
          </div>
        )}
        {summary && <div className="px-4 py-2 font-mono text-xs border-b border-[#1E293B] text-emerald-400">passed={summary.passed} · failed={summary.failed}</div>}
        <div className="flex-1 overflow-auto p-4">
          <table className="w-full font-mono text-xs">
            <thead><tr className="text-slate-500 text-left"><th>Test</th><th>Seed</th><th>Status</th><th>Coverage</th><th>Simulation</th></tr></thead>
            <tbody>
              {results.map((r) => (
                <tr key={`${r.index}-${r.seed}`} className="border-t border-[#1E293B]">
                  <td className="py-2">{r.name}</td><td>{r.seed ?? "—"}</td>
                  <td className={r.status === "done" ? "text-emerald-400" : r.status === "error" ? "text-red-400" : "text-amber-400"}>{r.status}</td>
                  <td className="text-slate-500">{r.coverage_overall != null ? `${r.coverage_overall}%` : "—"}</td>
                  <td className="text-slate-500">{r.simulation_id?.slice(0, 8)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!results.length && <div className="text-slate-500 font-mono text-xs">Testbench files are detected by kind/name. Configure seeds/workers and run.</div>}
        </div>
      </div>
    </div>
  );
}
