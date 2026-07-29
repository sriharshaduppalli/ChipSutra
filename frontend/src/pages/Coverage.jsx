import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API, api, getToken } from "@/lib/api";
import { Upload, Activity, Loader2, Target, GitCompare, Zap, Play } from "lucide-react";
import { toast } from "sonner";

export default function Coverage() {
  const navigate = useNavigate();
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [rtlFileIds, setRtlFileIds] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [holes, setHoles] = useState([]);
  const [plan, setPlan] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [beforeId, setBeforeId] = useState("");
  const [closure, setClosure] = useState(null);

  const loadProjects = useCallback(async () => {
    try {
      const { data } = await api.get("/projects");
      setProjects(Array.isArray(data) ? data : []);
    } catch {
      /* the page still works as a one-off parser without a project */
    }
  }, []);

  useEffect(() => { loadProjects(); }, [loadProjects]);

  const loadRuns = useCallback(async () => {
    if (!projectId) { setRuns([]); setRtlFileIds([]); return; }
    try {
      const [cov, proj] = await Promise.all([
        api.get(`/projects/${projectId}/coverage`),
        api.get(`/projects/${projectId}`),
      ]);
      setRuns(Array.isArray(cov.data) ? cov.data : []);
      setRtlFileIds(
        (proj.data.files || [])
          .filter((f) => ["v", "sv"].includes((f.ext || "").toLowerCase()))
          .map((f) => f.id),
      );
    } catch {
      toast.error("Could not load coverage runs for that project");
    }
  }, [projectId]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const loadHoles = useCallback(async () => {
    if (!projectId || !runId) { setHoles([]); return; }
    try {
      const { data } = await api.get(`/projects/${projectId}/coverage/${runId}/holes`, { params: { limit: 20 } });
      setHoles(data.holes || []);
    } catch {
      setHoles([]);
    }
  }, [projectId, runId]);

  useEffect(() => { loadHoles(); }, [loadHoles]);

  const selectRun = (id) => {
    setRunId(id);
    setPlan(null);
    setClosure(null);
    const doc = runs.find((r) => r.id === id);
    if (doc) setResult({ overall: doc.overall, metrics: doc.metrics || [], holes: doc.holes || [], count: (doc.metrics || []).length });
  };

  const upload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    if (projectId) fd.append("project_id", projectId);
    try {
      const res = await fetch(`${API}/coverage/parse`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setResult(data);
      setPlan(null);
      setClosure(null);
      toast.success(`Parsed ${data.count} coverage metrics`);
      if (data.coverage_run_id) {
        setRunId(data.coverage_run_id);
        loadRuns();
      }
    } catch { toast.error("Failed to parse"); }
    setBusy(false);
    e.target.value = "";
  };

  const buildPlan = async () => {
    if (!projectId || !runId) return toast.error("Pick a project and a persisted coverage run first");
    setPlanning(true);
    try {
      const { data } = await api.post(`/projects/${projectId}/coverage/${runId}/closure-plan`, {
        rtl_file_ids: rtlFileIds,
        limit: 12,
        base_seed: 1,
        max_cases: 6,
      });
      setPlan(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not build a closure plan");
    }
    setPlanning(false);
  };

  const compare = async (before) => {
    setBeforeId(before);
    setClosure(null);
    if (!before || !runId || before === runId) return;
    try {
      const { data } = await api.post(`/projects/${projectId}/coverage/closure-status`, {
        before_id: before,
        after_id: runId,
      });
      setClosure(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Could not compare coverage runs");
    }
  };

  const goGenerateHoleTests = () => {
    if (!projectId || !plan?.prompt) return toast.error("Build a closure plan first");
    navigate(`/app/projects/${projectId}`, {
      state: {
        module: "coverage_holes",
        prompt: plan.prompt,
        fileIds: rtlFileIds,
        autoGenerate: true,
      },
    });
  };

  const goApplyResimSeeds = () => {
    if (!projectId || !plan?.resim?.seeds?.length) return toast.error("Build a closure plan first");
    navigate(`/app/projects/${projectId}`, {
      state: {
        openRegression: true,
        seeds: plan.resim.seeds,
        coverage: plan.resim.coverage !== false,
      },
    });
  };

  const heatColor = (p) => {
    if (p >= 95) return "bg-emerald-500";
    if (p >= 80) return "bg-emerald-500/60";
    if (p >= 60) return "bg-amber-500/70";
    if (p >= 40) return "bg-amber-500";
    return "bg-red-500";
  };

  const prioColor = (p) => (p === "high" ? "text-red-400" : p === "medium" ? "text-amber-400" : "text-slate-300");

  return (
    <div className="p-8" data-testid="coverage-page">
      <div className="pin-badge mb-2 inline-block">ANALYSIS</div>
      <h1 className="font-display text-3xl font-bold mb-1">Coverage Analysis</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Upload a coverage report (.rpt / .log / .txt). We'll extract metrics and surface holes.</p>

      <div className="card-surface p-4 mb-6 flex flex-wrap items-center gap-3">
        <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">Project</span>
        <select
          value={projectId}
          onChange={(e) => { setProjectId(e.target.value); setRunId(""); setPlan(null); setClosure(null); setBeforeId(""); }}
          className="bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono min-w-[14rem]"
          data-testid="cov-project"
        >
          <option value="">none (parse only, nothing persisted)</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {projectId && (
          <>
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">Run</span>
            <select value={runId} onChange={(e) => selectRun(e.target.value)} className="bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-xs font-mono min-w-[18rem]" data-testid="cov-run">
              <option value="">select a persisted coverage run…</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {(r.created_at ? new Date(r.created_at).toLocaleString() : r.id.slice(0, 8))} · {r.overall}% · {r.filename || r.source || "run"}
                </option>
              ))}
            </select>
            <span className="font-mono text-[10px] text-slate-500">{runs.length} run(s) · {rtlFileIds.length} RTL file(s)</span>
          </>
        )}
        <span className="font-mono text-[10px] text-slate-500 flex-1">Pick a project to persist uploads and unlock the closure loop.</span>
      </div>

      <label className="block mb-6">
        <input type="file" accept=".rpt,.txt,.log,.csv,.xml,.json" onChange={upload} className="hidden" data-testid="cov-input" />
        <div className="card-surface p-8 text-center cursor-pointer hover:border-emerald-500/50 border-dashed">
          <Upload size={24} className="mx-auto mb-2 text-slate-400" />
          <div className="font-mono text-sm">{busy ? "Parsing..." : "Drop coverage report or click to upload"}</div>
          <div className="font-mono text-[10px] text-slate-500 mt-1">Lines like "Statement coverage: 87.5%" are auto-detected</div>
        </div>
      </label>

      {projectId && runId && (
        <div className="card-surface p-6 mb-6" data-testid="closure-loop">
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 inline-flex items-center gap-2"><Target size={12} className="text-emerald-400" /> Closure Loop</div>
            <button onClick={buildPlan} disabled={planning} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="closure-plan-btn">
              {planning ? <><Loader2 size={12} className="animate-spin" /> Planning</> : <><Activity size={12} /> Generate closure plan</>}
            </button>
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400 inline-flex items-center gap-1"><GitCompare size={11} /> compare vs</span>
            <select value={beforeId} onChange={(e) => compare(e.target.value)} className="bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-[10px] font-mono" data-testid="closure-compare">
              <option value="">earlier run…</option>
              {runs.filter((r) => r.id !== runId).map((r) => (
                <option key={r.id} value={r.id}>
                  {(r.created_at ? new Date(r.created_at).toLocaleString() : r.id.slice(0, 8))} · {r.overall}%
                </option>
              ))}
            </select>
          </div>

          {closure && (
            <div className="mb-4 border-l-2 border-emerald-500 pl-3 font-mono text-xs space-y-1" data-testid="closure-status">
              <div className={closure.improved ? "text-emerald-400" : "text-amber-400"}>
                {closure.overall_before}% → {closure.overall_after}% (Δ {closure.delta > 0 ? `+${closure.delta}` : closure.delta})
              </div>
              <div className="text-slate-400">closed: {closure.closed_holes?.length ? closure.closed_holes.join(", ") : "none"}</div>
              <div className="text-slate-400">new: {closure.new_holes?.length ? closure.new_holes.join(", ") : "none"}</div>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-red-400 mb-2">Ranked holes ({holes.length})</div>
              <div className="space-y-1 max-h-[320px] overflow-y-auto">
                {holes.map((h, i) => (
                  <div key={`${h.name}-${i}`} className="border border-[#1E293B] p-2" data-testid={`hole-${i}`}>
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="truncate">{h.name}</span>
                      <span className={prioColor(h.priority)}>{h.pct}% · {h.priority}</span>
                    </div>
                    <div className="font-mono text-[10px] text-slate-500 mt-1">{h.reason}</div>
                  </div>
                ))}
                {!holes.length && <div className="font-mono text-[10px] text-slate-500">No holes ranked for this run.</div>}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-widest text-emerald-400 mb-2">Suggested re-simulation</div>
              {plan ? (
                <div className="space-y-2">
                  <div className="font-mono text-[11px] text-slate-300">
                    seeds: <span className="text-emerald-400">{(plan.resim?.seeds || []).join(", ") || "—"}</span>
                  </div>
                  <div className="font-mono text-[11px] text-slate-300">
                    mode={plan.resim?.mode} · coverage={String(plan.resim?.coverage)}
                  </div>
                  <div className="font-mono text-[10px] text-slate-400">focus: {(plan.resim?.focus || []).join(", ") || "—"}</div>
                  <div className="font-mono text-[10px] text-slate-500">{plan.resim?.rationale}</div>
                  {plan.rtl_names?.length > 0 && <div className="font-mono text-[10px] text-slate-500">rtl: {plan.rtl_names.join(", ")}</div>}
                  <div className="flex flex-wrap gap-2 pt-2">
                    <button
                      type="button"
                      onClick={goGenerateHoleTests}
                      className="btn-neon text-xs inline-flex items-center gap-1"
                      data-testid="closure-generate-btn"
                    >
                      <Zap size={12} /> Generate hole tests
                    </button>
                    <button
                      type="button"
                      onClick={goApplyResimSeeds}
                      className="btn-outline-neon text-xs inline-flex items-center gap-1"
                      data-testid="closure-resim-btn"
                    >
                      <Play size={12} /> Apply seeds → Regression
                    </button>
                  </div>
                  <div className="font-mono text-[10px] uppercase tracking-widest text-slate-400 pt-2">Directed-test prompt</div>
                  <pre className="bg-[#0B0E14] border border-[#1E293B] p-3 font-mono text-[10px] text-slate-300 max-h-[200px] overflow-auto whitespace-pre-wrap">{plan.prompt}</pre>
                  <div className="font-mono text-[10px] text-slate-500">One-click generate opens the project on Coverage-Hole Tests with this prompt. Apply seeds opens the regression matrix prefilled.</div>
                </div>
              ) : (
                <div className="font-mono text-[10px] text-slate-500">Generate a plan to get deterministic seeds derived from the worst holes plus a directed-test prompt.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="card-surface p-6">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Overall</div>
            <div className="font-display text-6xl font-bold text-emerald-400">{result.overall}%</div>
            <div className="font-mono text-xs text-slate-400 mt-2">Averaged across {result.count} metrics</div>
            <div className="mt-4">
              <div className="font-mono text-xs text-slate-400 mb-2">Holes: {result.holes.length}</div>
              <div className="h-2 bg-[#0B0E14] border border-[#1E293B]">
                <div className={`h-full ${heatColor(result.overall)}`} style={{ width: `${result.overall}%` }}></div>
              </div>
            </div>
          </div>
          <div className="card-surface p-6 lg:col-span-2">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Heatmap</div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-[400px] overflow-y-auto">
              {result.metrics.map((m, i) => (
                <div key={i} className="border border-[#1E293B] p-3" data-testid={`metric-${i}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="font-mono text-[11px] text-slate-300 truncate">{m.name}</div>
                    <div className={`font-mono text-xs font-bold ${m.pct >= 90 ? 'text-emerald-400' : m.pct >= 70 ? 'text-amber-400' : 'text-red-400'}`}>{m.pct}%</div>
                  </div>
                  <div className="h-1 bg-[#0B0E14]">
                    <div className={`h-full ${heatColor(m.pct)}`} style={{ width: `${m.pct}%` }}></div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          {result.holes.length > 0 && (
            <div className="card-surface p-6 lg:col-span-3">
              <div className="font-mono text-xs uppercase tracking-widest text-red-400 mb-3">Coverage Holes ({result.holes.length})</div>
              <div className="space-y-1">
                {result.holes.map((h, i) => (
                  <div key={i} className="flex items-center justify-between border-l-2 border-red-500 pl-3 py-1 font-mono text-xs">
                    <span>{h.name}</span>
                    <span className="text-red-400">{h.pct}%</span>
                  </div>
                ))}
              </div>
              <div className="mt-4 font-mono text-[11px] text-slate-400">Tip: open a project → use "Coverage-Hole Tests" module to auto-generate closure tests.</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
