import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { FileText, Download } from "lucide-react";

export default function Reports() {
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [gens, setGens] = useState([]);

  useEffect(() => {
    api.get("/projects").then(r => setProjects(r.data));
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.get(`/projects/${selected}/generations`).then(r => setGens(r.data));
  }, [selected]);

  const download = (g) => {
    const ext = ["testbench","assertions","checkers","covergroups","spec2rtl","coverage_holes"].includes(g.module) ? "sv" : "md";
    const blob = new Blob([g.output || ""], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `chipsutra_${g.module}_${g.id.slice(0,8)}.${ext}`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-8" data-testid="reports-page">
      <div className="pin-badge mb-2 inline-block">ARTIFACTS</div>
      <h1 className="font-display text-3xl font-bold mb-1">Reports & Downloads</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Download every generation artifact you've produced.</p>

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
