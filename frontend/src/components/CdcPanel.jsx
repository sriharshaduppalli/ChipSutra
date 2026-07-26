import { useState } from "react";
import { api } from "@/lib/api";
import { GitBranch, Loader2, X, Play } from "lucide-react";
import { toast } from "sonner";

export default function CdcPanel({ project, selectedFileIds, onClose }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const rtlIds = selectedFileIds.filter((fid) => {
    const f = (project.files || []).find((x) => x.id === fid);
    return f && ["v", "sv"].includes((f.ext || "").toLowerCase());
  });
  const ids = rtlIds.length ? rtlIds : (project.files || []).filter((f) => ["v", "sv"].includes((f.ext || "").toLowerCase())).map((f) => f.id);

  const run = async () => {
    if (!ids.length) {
      toast.error("Select or upload at least one .v/.sv file");
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const { data } = await api.post("/cdc/analyze", {
        project_id: project.id,
        rtl_file_ids: ids,
      });
      setResult(data);
      toast.success(`CDC: ${data.counts?.cdc_warn || 0} warnings`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "CDC analysis failed");
    }
    setRunning(false);
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" data-testid="cdc-modal">
      <div className="card-surface w-full max-w-3xl h-[80vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <GitBranch size={16} className="text-emerald-400" />
            <div className="font-mono text-sm">CDC / RDC (experimental) · {project.name}</div>
            <span className="pin-badge text-amber-400 border-amber-500/40">v0 heuristic</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100" data-testid="cdc-close"><X size={16} /></button>
        </div>
        <div className="p-4 border-b border-[#1E293B] flex items-center gap-3">
          <div className="font-mono text-[10px] text-slate-500 flex-1">
            Regex clock-domain heuristics + 2FF detection. Not a Spyglass/Questa CDC replacement.
          </div>
          <button disabled={running || !ids.length} onClick={run} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="cdc-run">
            {running ? <><Loader2 size={12} className="animate-spin" /> Analyzing...</> : <><Play size={12} /> Analyze CDC</>}
          </button>
        </div>
        <div className="flex-1 overflow-auto bg-[#0B0E14] p-4 font-mono text-[11px]">
          {!result && !running && <div className="text-slate-500">Select RTL and run Analyze CDC.</div>}
          {result && (
            <>
              <div className="text-emerald-400 mb-2">
                clocks: {(result.clocks || []).join(", ") || "(none found)"} · warn={result.counts?.cdc_warn} info={result.counts?.cdc_info} rdc={result.counts?.rdc}
              </div>
              <div className="text-slate-500 mb-3">{result.disclaimer}</div>
              {(result.findings || []).map((f, i) => (
                <div key={i} className={`mb-2 ${f.severity === "warn" ? "text-amber-400" : "text-slate-300"}`}>
                  [{f.kind}/{f.severity}] {f.filename}: {f.signal} ({f.from_domain} → {f.to_domain}) — {f.note}
                </div>
              ))}
              {(result.findings || []).length === 0 && <div className="text-emerald-400">No CDC/RDC findings.</div>}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
