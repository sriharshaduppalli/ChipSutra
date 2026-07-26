import { useEffect, useMemo, useState } from "react";
import { API, getToken } from "@/lib/api";
import { Upload, Search, ZoomIn } from "lucide-react";
import { toast } from "sonner";
import { useSearchParams } from "react-router-dom";

export default function Waveform() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState([]);
  const [cellW, setCellW] = useState(32);
  const [cursorIndex, setCursorIndex] = useState(null);
  const [params] = useSearchParams();
  const projectId = params.get("pid");
  const fileId = params.get("file_id");

  const parseProjectFile = async (signalIds = null) => {
    if (!projectId || !fileId) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/waveform/parse-project`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ project_id: projectId, file_id: fileId, signal_ids: signalIds }),
      });
      if (!res.ok) throw new Error();
      const parsed = await res.json();
      setData(parsed);
      if (!selectedIds.length) setSelectedIds(parsed.tracks.map((t) => t.id));
    } catch {
      toast.error("Failed to load project VCD");
    }
    setBusy(false);
  };

  useEffect(() => {
    if (projectId && fileId) parseProjectFile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, fileId]);

  const upload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch(`${API}/waveform/parse`, {
        method: "POST",
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      });
      if (!res.ok) throw new Error();
      const parsed = await res.json();
      setData(parsed);
      setSelectedIds(parsed.tracks.map((t) => t.id));
      toast.success("VCD parsed");
    } catch { toast.error("Failed to parse VCD"); }
    setBusy(false);
    e.target.value = "";
  };

  const filteredSignals = useMemo(
    () => (data?.signal_index || []).filter((s) => s.path.toLowerCase().includes(query.toLowerCase())),
    [data, query],
  );

  const toggleSignal = (id) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-64));
  };

  const refreshSignals = () => {
    if (projectId && fileId) parseProjectFile(selectedIds);
    else if (data) setData({ ...data, tracks: data.tracks.filter((t) => selectedIds.includes(t.id)) });
  };

  return (
    <div className="p-8" data-testid="waveform-page">
      <div className="pin-badge mb-2 inline-block">VCD VIEWER</div>
      <h1 className="font-display text-3xl font-bold mb-1">Waveform Visualization</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Hierarchy/search, selected traces, zoom and cursor for VCD debug.</p>

      <label className="block mb-6">
        <input type="file" accept=".vcd" onChange={upload} className="hidden" data-testid="vcd-input" />
        <div className="card-surface p-8 text-center cursor-pointer hover:border-emerald-500/50 border-dashed">
          <Upload size={24} className="mx-auto mb-2 text-slate-400" />
          <div className="font-mono text-sm">{busy ? "Parsing..." : "Drop VCD file or click to upload"}</div>
          <div className="font-mono text-[10px] text-slate-500 mt-1">.vcd — up to 512 indexed signals, 64 rendered tracks</div>
        </div>
      </label>

      {data && (
        <div className="card-surface p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="font-mono text-xs text-slate-400">
              Timescale: <span className="text-emerald-400">{data.timescale}</span> · Signals: <span className="text-emerald-400">{data.signal_count}</span> · Steps: <span className="text-emerald-400">{data.times.length}</span>
              {data.truncated && <span className="text-amber-400"> · sampled</span>}
            </div>
            <div className="font-mono text-xs text-emerald-400">cursor: {cursorIndex == null ? "—" : data.times[cursorIndex]}</div>
          </div>
          <div className="grid grid-cols-12 gap-3">
            <div className="col-span-3 border border-[#1E293B] p-2 max-h-[560px] overflow-auto">
              <div className="flex items-center gap-1 mb-2"><Search size={12} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="signal path" className="w-full bg-[#0B0E14] px-2 py-1 text-xs font-mono" /></div>
              <button onClick={refreshSignals} className="btn-outline-neon text-[10px] w-full mb-2">Render selected ({selectedIds.length})</button>
              {filteredSignals.map((s) => (
                <label key={s.id} className="flex items-center gap-2 py-1 font-mono text-[10px] text-slate-300">
                  <input type="checkbox" checked={selectedIds.includes(s.id)} onChange={() => toggleSignal(s.id)} />
                  <span className="truncate" title={s.path}>{s.path}</span><span className="text-slate-500">[{s.width}]</span>
                </label>
              ))}
            </div>
            <div className="col-span-9">
              <div className="flex items-center gap-2 mb-2 font-mono text-[10px] text-slate-400">
                <ZoomIn size={12} /> zoom
                <input type="range" min={12} max={80} value={cellW} onChange={(e) => setCellW(Number(e.target.value))} />
              </div>
              <div className="overflow-x-auto scanline" onMouseLeave={() => setCursorIndex(null)}>
                <table className="border-collapse font-mono text-[10px]">
                  <tbody>
                    {data.tracks.map((t) => (
                      <WaveRow key={t.id} track={t} times={data.times} cellW={cellW} cursorIndex={cursorIndex} setCursorIndex={setCursorIndex} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          {data.tracks.length === 0 && (
            <div className="text-center font-mono text-xs text-slate-500 py-8">
              No signals extracted. Check that the VCD file has valid $var and value change lines.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function WaveRow({ track, times, cellW, cursorIndex, setCursorIndex }) {
  const rowH = 40;
  const svgW = times.length * cellW;
  // Convert values to path
  let path = "";
  const midH = rowH / 2;
  const highY = 6;
  const lowY = rowH - 6;

  const isSingleBit = track.width === 1;

  if (isSingleBit) {
    let lastY = null;
    for (let i = 0; i < track.values.length; i++) {
      const v = track.values[i];
      const y = v === "1" ? highY : (v === "0" ? lowY : midH);
      const x1 = i * cellW;
      const x2 = x1 + cellW;
      if (lastY === null) path += `M ${x1} ${y} `;
      else if (lastY !== y) path += `L ${x1} ${y} `;
      path += `L ${x2} ${y} `;
      lastY = y;
    }
  }

  return (
    <tr className="border-b border-[#1E293B]">
      <td className="pr-4 py-1 text-slate-300 whitespace-nowrap sticky left-0 bg-[#121721] min-w-[180px] max-w-[240px] truncate">{track.name} <span className="text-slate-500">[{track.width}]</span></td>
      <td className="p-0">
        <svg
          width={svgW}
          height={rowH}
          className="block"
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const x = e.clientX - rect.left;
            setCursorIndex(Math.max(0, Math.min(times.length - 1, Math.floor(x / cellW))));
          }}
        >
          {track.values.map((v, i) => (
            <line key={i} x1={i * cellW} y1={0} x2={i * cellW} y2={rowH} stroke="#1E293B" strokeWidth="1" />
          ))}
          {isSingleBit ? (
            <path d={path} fill="none" stroke="#10B981" strokeWidth="1.5" />
          ) : (
            track.values.map((v, i) => (
              <g key={i}>
                <rect x={i * cellW + 2} y={8} width={cellW - 4} height={rowH - 16} fill="none" stroke="#0EA5E9" strokeWidth="1" />
                <text x={i * cellW + cellW / 2} y={rowH / 2 + 3} textAnchor="middle" fill="#0EA5E9" fontSize="9" fontFamily="JetBrains Mono">{(v.length > 6 ? v.slice(0,5)+'…' : v)}</text>
              </g>
            ))
          )}
          {cursorIndex != null && (
            <line x1={cursorIndex * cellW} y1={0} x2={cursorIndex * cellW} y2={rowH} stroke="#F59E0B" strokeWidth="1.5" />
          )}
        </svg>
      </td>
    </tr>
  );
}
