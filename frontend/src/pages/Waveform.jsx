import { useState } from "react";
import { API, getToken } from "@/lib/api";
import { Upload, Waves } from "lucide-react";
import { toast } from "sonner";

export default function Waveform() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

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
      setData(await res.json());
      toast.success("VCD parsed");
    } catch { toast.error("Failed to parse VCD"); }
    setBusy(false);
    e.target.value = "";
  };

  return (
    <div className="p-8" data-testid="waveform-page">
      <div className="pin-badge mb-2 inline-block">VCD VIEWER</div>
      <h1 className="font-display text-3xl font-bold mb-1">Waveform Visualization</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Upload a VCD file. We'll render a WaveDrom-style timing view.</p>

      <label className="block mb-6">
        <input type="file" accept=".vcd" onChange={upload} className="hidden" data-testid="vcd-input" />
        <div className="card-surface p-8 text-center cursor-pointer hover:border-emerald-500/50 border-dashed">
          <Upload size={24} className="mx-auto mb-2 text-slate-400" />
          <div className="font-mono text-sm">{busy ? "Parsing..." : "Drop VCD file or click to upload"}</div>
          <div className="font-mono text-[10px] text-slate-500 mt-1">.vcd — up to 32 signals × 200 time steps rendered</div>
        </div>
      </label>

      {data && (
        <div className="card-surface p-4">
          <div className="flex items-center justify-between mb-4">
            <div className="font-mono text-xs text-slate-400">Timescale: <span className="text-emerald-400">{data.timescale}</span> · Signals: <span className="text-emerald-400">{data.signal_count}</span> · Steps: <span className="text-emerald-400">{data.times.length}</span></div>
          </div>
          <div className="overflow-x-auto scanline">
            <table className="border-collapse font-mono text-[10px] w-full">
              <tbody>
                {data.tracks.map((t) => (
                  <WaveRow key={t.id} track={t} times={data.times} />
                ))}
              </tbody>
            </table>
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

function WaveRow({ track, times }) {
  const cellW = 32;
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
        <svg width={svgW} height={rowH} className="block">
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
        </svg>
      </td>
    </tr>
  );
}
