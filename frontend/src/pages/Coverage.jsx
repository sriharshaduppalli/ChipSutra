import { useState } from "react";
import { API, getToken } from "@/lib/api";
import { Upload, Activity } from "lucide-react";
import { toast } from "sonner";

export default function Coverage() {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const upload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch(`${API}/coverage/parse`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      if (!res.ok) throw new Error();
      const data = await res.json();
      setResult(data);
      toast.success(`Parsed ${data.count} coverage metrics`);
    } catch { toast.error("Failed to parse"); }
    setBusy(false);
    e.target.value = "";
  };

  const heatColor = (p) => {
    if (p >= 95) return "bg-emerald-500";
    if (p >= 80) return "bg-emerald-500/60";
    if (p >= 60) return "bg-amber-500/70";
    if (p >= 40) return "bg-amber-500";
    return "bg-red-500";
  };

  return (
    <div className="p-8" data-testid="coverage-page">
      <div className="pin-badge mb-2 inline-block">ANALYSIS</div>
      <h1 className="font-display text-3xl font-bold mb-1">Coverage Analysis</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Upload a coverage report (.rpt / .log / .txt). We'll extract metrics and surface holes.</p>

      <label className="block mb-6">
        <input type="file" accept=".rpt,.txt,.log,.csv" onChange={upload} className="hidden" data-testid="cov-input" />
        <div className="card-surface p-8 text-center cursor-pointer hover:border-emerald-500/50 border-dashed">
          <Upload size={24} className="mx-auto mb-2 text-slate-400" />
          <div className="font-mono text-sm">{busy ? "Parsing..." : "Drop coverage report or click to upload"}</div>
          <div className="font-mono text-[10px] text-slate-500 mt-1">Lines like "Statement coverage: 87.5%" are auto-detected</div>
        </div>
      </label>

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
