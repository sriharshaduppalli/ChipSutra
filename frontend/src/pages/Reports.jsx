import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FileText, Download, ShieldAlert } from "lucide-react";

const TILE_COLOR = {
  pass: "text-emerald-400 border-emerald-500/40",
  fail: "text-red-400 border-red-500/40",
  skip: "text-amber-400 border-amber-500/40",
  missing: "text-slate-500 border-[#1E293B]",
};

export default function Reports() {
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [gens, setGens] = useState([]);
  const [signoff, setSignoff] = useState(null);
  const [trace, setTrace] = useState(null);

  useEffect(() => {
    api.get("/projects").then(r => setProjects(r.data));
  }, []);

  useEffect(() => {
    if (!selected) {
      setGens([]);
      setSignoff(null);
      setTrace(null);
      return;
    }
    api.get(`/projects/${selected}/generations`).then(r => setGens(r.data));
    api.get(`/projects/${selected}/signoff`).then(r => setSignoff(r.data)).catch(() => setSignoff(null));
    api.get(`/projects/${selected}/traceability`).then(r => setTrace(r.data)).catch(() => setTrace(null));
  }, [selected]);

  const download = (g) => {
    const ext = ["testbench","assertions","checkers","covergroups","spec2rtl","coverage_holes"].includes(g.module) ? "sv" : "md";
    const blob = new Blob([g.output || ""], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `chipsutra_${g.module}_${g.id.slice(0,8)}.${ext}`; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadSignoff = async () => {
    if (!selected) return;
    const { data } = await api.get(`/projects/${selected}/signoff.zip`, { responseType: "blob" });
    const url = URL.createObjectURL(data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chipsutra_signoff_${selected.slice(0, 8)}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-8" data-testid="reports-page">
      <div className="pin-badge mb-2 inline-block">ARTIFACTS</div>
      <h1 className="font-display text-3xl font-bold mb-1">Reports & Downloads</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Download every generation artifact you've produced. Readiness tiles are not vendor sign-off.</p>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-4 card-surface p-4">
          <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Projects</div>
          <div className="space-y-1 max-h-[500px] overflow-y-auto">
            {projects.map(p => (
              <button key={p.id} onClick={() => setSelected(p.id)} className={`w-full text-left p-2 font-mono text-xs ${selected === p.id ? 'bg-emerald-500/10 text-emerald-400 border-l-2 border-emerald-500' : 'text-slate-300 hover:bg-[#1A212D] border-l-2 border-transparent'}`} data-testid={`rp-${p.id}`}>
                <div>{p.name}</div>
                <div className="text-[10px] text-slate-500">{p.design_type} · {p.language}</div>
              </button>
            ))}
            {projects.length === 0 && <div className="font-mono text-[11px] text-slate-500 text-center py-4">No projects yet</div>}
          </div>
        </div>
        <div className="col-span-12 md:col-span-8 card-surface p-4">
          {signoff && selected && (
            <div className="mb-6" data-testid="signoff-board">
              <div className="flex items-center justify-between mb-2">
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400">
                  Readiness {signoff.score}/100
                </div>
                <button
                  type="button"
                  onClick={downloadSignoff}
                  className="btn-outline-neon text-xs inline-flex items-center gap-1"
                  data-testid="signoff-zip"
                >
                  <Download size={12} /> sign-off zip
                </button>
              </div>
              <div className="flex items-start gap-2 font-mono text-[10px] text-amber-400/90 mb-3">
                <ShieldAlert size={12} className="mt-0.5 shrink-0" />
                ChipSutra does not claim vendor sign-off (Questa/VCS/Xcelium UCIS).
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3">
                {(signoff.tiles || []).map((t) => (
                  <div
                    key={t.name}
                    className={`border px-2 py-2 ${TILE_COLOR[t.status] || TILE_COLOR.missing}`}
                    data-testid={`signoff-tile-${t.name}`}
                  >
                    <div className="font-mono text-[10px] uppercase tracking-widest">{t.name}</div>
                    <div className="font-mono text-xs">{t.status}</div>
                    {t.detail && <div className="font-mono text-[10px] text-slate-500 mt-1">{t.detail}</div>}
                  </div>
                ))}
              </div>
              {(signoff.residual_risk || []).length > 0 && (
                <ul className="font-mono text-[10px] text-slate-500 space-y-0.5 mb-4">
                  {signoff.residual_risk.slice(0, 6).map((r) => (
                    <li key={r}>· {r}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {trace && selected && (
            <div className="mb-6" data-testid="trace-matrix">
              <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">
                Traceability {trace.coverage_pct ?? 0}% · {trace.counts?.covered || 0}/{trace.counts?.plan || 0} plan items
              </div>
              <div className="font-mono text-[10px] text-slate-500 mb-2">
                Sources: {["testplan", "tb", "sva", "covergroups"].filter((k) => trace.sources?.[k]).join(", ") || "none yet"}
                {trace.counts?.sva != null ? ` · SVA ${trace.counts.sva}` : ""}
                {trace.counts?.coverpoints != null ? ` · CG ${trace.counts.coverpoints}` : ""}
              </div>
              <div className="space-y-1 max-h-[240px] overflow-y-auto mb-3">
                {(trace.rows || []).slice(0, 24).map((r) => (
                  <div key={r.id} className="flex items-start justify-between gap-2 border border-[#1E293B] px-2 py-1" data-testid={`trace-row-${r.id}`}>
                    <div className="min-w-0">
                      <div className="font-mono text-[11px] text-slate-200 truncate">{r.id} · {r.title}</div>
                      <div className="font-mono text-[10px] text-slate-500 truncate">
                        {(r.hits || []).map((h) => h.id).join(", ") || "no TB / SVA / CG hit"}
                      </div>
                    </div>
                    <span className={`font-mono text-[10px] shrink-0 ${r.covered ? "text-emerald-400" : "text-amber-400"}`}>
                      {r.covered ? "covered" : "gap"}
                    </span>
                  </div>
                ))}
                {!(trace.rows || []).length && (
                  <div className="font-mono text-[10px] text-slate-500">Generate a testplan + TB to populate the matrix.</div>
                )}
              </div>
              {(trace.orphans || []).length > 0 && (
                <div className="font-mono text-[10px] text-slate-500 mb-4">
                  Orphan checkers: {trace.orphans.slice(0, 8).map((o) => o.id).join(", ")}
                </div>
              )}
            </div>
          )}
          <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Generation Artifacts</div>
          {!selected ? (
            <div className="font-mono text-xs text-slate-500 text-center py-16">Select a project on the left.</div>
          ) : gens.length === 0 ? (
            <div className="font-mono text-xs text-slate-500 text-center py-16">No artifacts for this project yet.</div>
          ) : (
            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {gens.map(g => (
                <div key={g.id} className="border border-[#1E293B] p-3 flex items-start gap-3" data-testid={`report-${g.id}`}>
                  <FileText size={16} className="text-emerald-400 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-sm">{g.module}</div>
                    <div className="font-mono text-[10px] text-slate-500">{g.model} · {new Date(g.created_at).toLocaleString()} · {g.status}</div>
                    {g.output && <div className="font-mono text-[11px] text-slate-400 mt-1 line-clamp-2 whitespace-pre-wrap">{g.output.slice(0, 200)}...</div>}
                  </div>
                  {g.output && (
                    <button onClick={() => download(g)} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid={`report-dl-${g.id}`}>
                      <Download size={12} /> download
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
