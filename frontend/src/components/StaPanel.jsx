import { useCallback, useEffect, useMemo, useState } from "react";
import { API, api, getToken } from "@/lib/api";
import { Timer, Loader2, X, Play, History } from "lucide-react";
import { toast } from "sonner";

export default function StaPanel({ project, selectedFileIds, onClose }) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState(null);
  const [note, setNote] = useState(null);
  const [engine, setEngine] = useState(null);
  const [resolvedTop, setResolvedTop] = useState(null);
  const [runs, setRuns] = useState([]);
  const [netlistId, setNetlistId] = useState("");
  const [libertyId, setLibertyId] = useState("");
  const [sdcId, setSdcId] = useState("");
  const [topModule, setTopModule] = useState("");
  const [clockName, setClockName] = useState("clk");
  const [periodNs, setPeriodNs] = useState(10);

  const files = useMemo(() => project.files || [], [project.files]);
  const extOf = (f) => (f.ext || "").toLowerCase();

  const netlists = useMemo(
    () => files.filter((f) => ["v", "sv"].includes(extOf(f))),
    [files],
  );
  const liberties = useMemo(
    () => files.filter((f) => extOf(f) === "lib" || /\.lib$/i.test(f.original_filename || "")),
    [files],
  );
  const sdcs = useMemo(
    () => files.filter((f) => extOf(f) === "sdc" || /\.sdc$/i.test(f.original_filename || "")),
    [files],
  );

  // Preselect whatever the user highlighted on the project page, else the synth netlist.
  useEffect(() => {
    if (netlistId) return;
    const picked = netlists.find((f) => selectedFileIds.includes(f.id));
    const synth = netlists.find((f) => /^synth_netlist/i.test(f.original_filename || ""));
    if (picked || synth) setNetlistId((picked || synth).id);
  }, [netlistId, netlists, selectedFileIds]);

  useEffect(() => {
    if (!libertyId && liberties.length === 1) setLibertyId(liberties[0].id);
  }, [libertyId, liberties]);

  useEffect(() => {
    if (!sdcId && sdcs.length === 1) setSdcId(sdcs[0].id);
  }, [sdcId, sdcs]);

  const loadRuns = useCallback(async () => {
    try {
      const { data } = await api.get(`/projects/${project.id}/sta-runs`);
      setRuns(Array.isArray(data) ? data : []);
    } catch {
      /* history is optional */
    }
  }, [project.id]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const showRun = (run) => {
    const runStats = run.stats || {};
    setStats(run.stats || null);
    setNote(run.note || null);
    setStatus(run.status || null);
    // A mock run still records engine "opensta" in stats; the status_hint is what marks it.
    setEngine(run.status === "mock" || runStats.status_hint === "mock" ? "mock" : runStats.engine || null);
    setResolvedTop(run.top_module || null);
    setLogs((run.log || "").split("\n").filter(Boolean).map((line) => ({ level: "info", line })));
  };

  const run = async () => {
    setRunning(true);
    setLogs([]); setStats(null); setStatus(null); setNote(null); setEngine(null); setResolvedTop(null);
    try {
      const res = await fetch(`${API}/sta/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          netlist_file_id: netlistId || null,
          liberty_file_id: libertyId || null,
          sdc_file_id: sdcId || null,
          top_module: topModule || null,
          clock_name: clockName || "clk",
          period_ns: Number(periodNs) || 10.0,
          max_paths: 10,
        }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "STA stream failed");
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
            if (event.type === "meta") {
              setEngine(event.engine);
              setResolvedTop(event.top_module || null);
            }
            else if (event.type === "log") setLogs((prev) => [...prev, event]);
            else if (event.type === "stats") {
              setStats(event.stats || null);
              if (event.note) setNote(event.note);
            }
            else if (event.type === "done") {
              setStatus(event.status);
              if (event.stats) setStats(event.stats);
              if (event.note) setNote(event.note);
            }
          } catch {}
        }
      }
      loadRuns();
    } catch (e) {
      toast.error(e.message || "STA run failed");
    }
    setRunning(false);
  };

  const paths = stats?.paths || [];
  const isMock = status === "mock" || engine === "mock" || stats?.status_hint === "mock";
  const wns = stats?.wns;
  const tns = stats?.tns;
  const slackClass = (v) => (typeof v === "number" ? (v < 0 ? "text-red-400" : "text-emerald-400") : "text-slate-500");

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" data-testid="sta-modal">
      <div className="card-surface w-full max-w-5xl h-[84vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Timer size={16} className="text-emerald-400" />
            <span className="font-mono text-sm">OpenSTA Timing · {project.name}</span>
            {engine && <span className={`pin-badge ${engine === "mock" ? "text-amber-400 border-amber-500/40" : "text-emerald-400 border-emerald-500/40"}`}>{engine}</span>}
            {resolvedTop && <span className="font-mono text-[10px] text-slate-500">top={resolvedTop}</span>}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100" data-testid="sta-close"><X size={16} /></button>
        </div>

        <div className="p-4 border-b border-[#1E293B] grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="font-mono text-[10px] text-slate-400">
            NETLIST
            <select value={netlistId} onChange={(e) => setNetlistId(e.target.value)} className="w-full mt-1 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono text-slate-200" data-testid="sta-netlist">
              <option value="">auto (newest synth_netlist)</option>
              {netlists.map((f) => <option key={f.id} value={f.id}>{f.original_filename}</option>)}
            </select>
          </label>
          <label className="font-mono text-[10px] text-slate-400">
            LIBERTY (.lib)
            <select value={libertyId} onChange={(e) => setLibertyId(e.target.value)} className="w-full mt-1 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono text-slate-200" data-testid="sta-liberty">
              <option value="">none (mock run)</option>
              {liberties.map((f) => <option key={f.id} value={f.id}>{f.original_filename}</option>)}
            </select>
          </label>
          <label className="font-mono text-[10px] text-slate-400">
            SDC
            <select value={sdcId} onChange={(e) => setSdcId(e.target.value)} className="w-full mt-1 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono text-slate-200" data-testid="sta-sdc">
              <option value="">auto stub from clock/period</option>
              {sdcs.map((f) => <option key={f.id} value={f.id}>{f.original_filename}</option>)}
            </select>
          </label>
        </div>

        <div className="p-4 border-b border-[#1E293B] flex flex-wrap gap-3 items-center">
          <input value={topModule} onChange={(e) => setTopModule(e.target.value)} placeholder="top module (auto)" className="flex-1 min-w-[10rem] bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono" data-testid="sta-top" />
          <span className="font-mono text-[10px] text-slate-400">CLOCK</span>
          <input value={clockName} onChange={(e) => setClockName(e.target.value)} className="w-24 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono" data-testid="sta-clock" />
          <span className="font-mono text-[10px] text-slate-400">PERIOD ns</span>
          <input type="number" min="0.1" step="0.1" value={periodNs} onChange={(e) => setPeriodNs(e.target.value)} className="w-24 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono" data-testid="sta-period" />
          <button onClick={run} disabled={running} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="sta-run">
            {running ? <><Loader2 size={12} className="animate-spin" /> Running</> : <><Play size={12} /> Run STA</>}
          </button>
        </div>

        {(typeof wns === "number" || typeof tns === "number") && (
          <div className="px-4 py-3 border-b border-[#1E293B] flex flex-wrap gap-8 items-center" data-testid="sta-summary">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">WNS</div>
              <div className={`font-display text-2xl font-bold ${slackClass(wns)}`}>{typeof wns === "number" ? `${wns} ns` : "—"}</div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">TNS</div>
              <div className={`font-display text-2xl font-bold ${slackClass(tns)}`}>{typeof tns === "number" ? `${tns} ns` : "—"}</div>
            </div>
            <div className="font-mono text-xs">
              <span className={stats?.violated ? "text-red-400" : "text-emerald-400"}>
                {stats?.violated ? "TIMING VIOLATED" : "no negative slack reported"}
              </span>
              <span className="text-slate-500"> · {paths.length} path(s) reported</span>
            </div>
          </div>
        )}

        {(note || isMock) && (
          <div className="px-4 py-2 border-b border-[#1E293B] font-mono text-[10px] text-amber-400/90" data-testid="sta-note">
            {note || "Mock run — install OpenSTA (`sta`) and upload a liberty (.lib) for real timing numbers."}
            {stats?.missing?.length ? <span className="text-slate-400"> · missing: {stats.missing.join(", ")}</span> : null}
          </div>
        )}

        <div className="flex-1 overflow-auto grid grid-cols-1 lg:grid-cols-2">
          <div className="overflow-auto bg-[#0B0E14] p-4 font-mono text-[11px] border-r border-[#1E293B]">
            {logs.map((l, i) => (
              <div key={i} className={l.level === "error" ? "text-red-400" : l.level === "warn" ? "text-amber-400" : "text-slate-300"}>{l.line}</div>
            ))}
            {!logs.length && !running && (
              <div className="text-slate-500">Runs OpenSTA on a synthesized netlist. Without `sta` on PATH or a liberty file you get a mock run that tells you exactly what is missing.</div>
            )}
            {status && <div className={`mt-4 ${status === "done" ? "text-emerald-400" : status === "mock" ? "text-amber-400" : "text-red-400"}`}>[{status.toUpperCase()}]</div>}
          </div>

          <div className="overflow-auto p-4">
            <div className="font-mono text-[10px] uppercase tracking-widest text-slate-400 mb-2">Timing paths</div>
            <table className="w-full font-mono text-[11px]">
              <thead><tr className="text-slate-500 text-left"><th>Startpoint</th><th>Endpoint</th><th>Slack</th><th>Status</th></tr></thead>
              <tbody>
                {paths.map((p, i) => (
                  <tr key={i} className="border-t border-[#1E293B]" data-testid={`sta-path-${i}`}>
                    <td className="py-1 pr-2 truncate max-w-[10rem]" title={p.startpoint || ""}>{p.startpoint || "—"}</td>
                    <td className="pr-2 truncate max-w-[10rem]" title={p.endpoint || ""}>{p.endpoint || "—"}</td>
                    <td className={slackClass(p.slack)}>{p.slack}</td>
                    <td className={p.status === "VIOLATED" ? "text-red-400" : "text-emerald-400"}>{p.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!paths.length && <div className="text-slate-500 font-mono text-[11px]">No paths yet — run STA with a liberty file to populate report_checks output.</div>}

            {stats?.errors?.length > 0 && (
              <div className="mt-4">
                <div className="font-mono text-[10px] uppercase tracking-widest text-red-400 mb-1">Errors</div>
                {stats.errors.map((e, i) => <div key={i} className="font-mono text-[10px] text-red-400/90">{e}</div>)}
              </div>
            )}

            <div className="mt-6">
              <div className="font-mono text-[10px] uppercase tracking-widest text-slate-400 mb-2 inline-flex items-center gap-1"><History size={11} /> Previous runs ({runs.length})</div>
              <div className="space-y-1">
                {runs.map((r) => (
                  <button key={r.id} onClick={() => showRun(r)} className="w-full text-left p-2 hover:bg-[#1A212D] font-mono text-[10px] border border-[#1E293B]" data-testid={`sta-run-${r.id}`}>
                    <span className={r.status === "done" ? "text-emerald-400" : r.status === "mock" ? "text-amber-400" : "text-red-400"}>{r.status}</span>
                    <span className="text-slate-500"> · {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</span>
                    <span className="text-slate-400"> · wns={r.stats?.wns ?? "—"} tns={r.stats?.tns ?? "—"}</span>
                  </button>
                ))}
                {!runs.length && <div className="font-mono text-[10px] text-slate-500">No STA runs yet.</div>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
