import { useMemo, useState } from "react";
import { API, getToken } from "@/lib/api";
import { FlaskConical, Loader2, X, Play, CheckCircle2, Circle, XCircle, MinusCircle } from "lucide-react";
import { toast } from "sonner";

const STAGE_ORDER = ["lint", "sim", "synth", "sta"];

function StageIcon({ state }) {
  if (state === "running") return <Loader2 size={14} className="animate-spin text-emerald-400" />;
  if (state === "done") return <CheckCircle2 size={14} className="text-emerald-400" />;
  if (state === "mock") return <MinusCircle size={14} className="text-amber-400" />;
  if (state === "error") return <XCircle size={14} className="text-red-400" />;
  return <Circle size={14} className="text-slate-600" />;
}

export default function LabPipelinePanel({ project, selectedFileIds, onClose, onArtifacts }) {
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [topModule, setTopModule] = useState("");
  const [skipSim, setSkipSim] = useState(false);
  const [simTime, setSimTime] = useState(1000);
  const [clockName, setClockName] = useState("clk");
  const [periodNs, setPeriodNs] = useState(10);
  const [stageState, setStageState] = useState({});
  const [activeStage, setActiveStage] = useState(null);
  const [results, setResults] = useState([]);

  const files = useMemo(() => project.files || [], [project.files]);
  const selected = selectedFileIds.filter((fid) => {
    const f = files.find((x) => x.id === fid);
    return f && ["v", "sv"].includes((f.ext || "").toLowerCase());
  });
  const rtlIds = selected.length
    ? selected.filter((fid) => {
        const f = files.find((x) => x.id === fid);
        const name = (f?.original_filename || "").toLowerCase();
        return f?.kind !== "tb" && !name.endsWith("_tb.sv") && !name.endsWith("_tb.v");
      })
    : files
        .filter((f) => {
          const ext = (f.ext || "").toLowerCase();
          const name = (f.original_filename || "").toLowerCase();
          return (
            ["v", "sv"].includes(ext) &&
            f.kind !== "tb" &&
            !name.endsWith("_tb.sv") &&
            !name.endsWith("_tb.v") &&
            !name.startsWith("synth_netlist")
          );
        })
        .map((f) => f.id);

  const tbFile =
    files.find((f) => selectedFileIds.includes(f.id) && (f.kind === "tb" || /_tb\.(sv|v)$/i.test(f.original_filename || ""))) ||
    files.find((f) => f.kind === "tb" || /_tb\.(sv|v)$/i.test(f.original_filename || ""));

  const libertyFile = files.find((f) => (f.ext || "").toLowerCase() === "lib" || /\.lib$/i.test(f.original_filename || ""));
  const sdcFile = files.find((f) => (f.ext || "").toLowerCase() === "sdc" || /\.sdc$/i.test(f.original_filename || ""));

  const run = async () => {
    if (!rtlIds.length) return toast.error("Upload or select synthesizable RTL first");
    setRunning(true);
    setLogs([]);
    setStatus(null);
    setResults([]);
    setActiveStage(null);
    setStageState({});
    try {
      const res = await fetch(`${API}/lab/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({
          project_id: project.id,
          rtl_file_ids: rtlIds,
          tb_file_id: tbFile?.id || null,
          top_module: topModule || null,
          skip_sim: skipSim || !tbFile,
          sim_time_ns: Number(simTime) || 1000,
          liberty_file_id: libertyFile?.id || null,
          sdc_file_id: sdcFile?.id || null,
          clock_name: clockName || "clk",
          period_ns: Number(periodNs) || 10,
          stop_on_fail: true,
          scaffold_sta: true,
        }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Lab stream failed");
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
            if (event.type === "meta" && Array.isArray(event.stages)) {
              const init = {};
              for (const s of event.stages) init[s.id] = "pending";
              setStageState(init);
            } else if (event.type === "stage_start") {
              setActiveStage(event.stage);
              setStageState((prev) => ({ ...prev, [event.stage]: "running" }));
            } else if (event.type === "stage_done") {
              setStageState((prev) => ({ ...prev, [event.stage]: event.status || "error" }));
            } else if (event.type === "log") {
              setLogs((prev) => [
                ...prev,
                {
                  level: event.level || "info",
                  line: event.stage ? `[${event.stage}] ${event.line}` : event.line,
                },
              ]);
            } else if (event.type === "done") {
              setStatus(event.status);
              setResults(Array.isArray(event.results) ? event.results : []);
              setActiveStage(null);
              if (onArtifacts) onArtifacts();
            }
          } catch {
            /* ignore partial JSON */
          }
        }
      }
    } catch (e) {
      toast.error(e.message || "Lab pipeline failed");
      setStatus("error");
    }
    setRunning(false);
  };

  const statusColor =
    status === "done" ? "text-emerald-400" : status === "partial" ? "text-amber-400" : status === "error" ? "text-red-400" : "text-slate-500";

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" data-testid="lab-modal">
      <div className="card-surface w-full max-w-5xl h-[84vh] flex flex-col">
        <div className="border-b border-[#1E293B] px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FlaskConical size={16} className="text-emerald-400" />
            <span className="font-mono text-sm">Open Lab · lint → sim → synth → STA · {project.name}</span>
            {status && <span className={`pin-badge ${statusColor}`}>{status}</span>}
          </div>
          <button onClick={onClose}><X size={16} /></button>
        </div>

        <div className="p-4 border-b border-[#1E293B] flex flex-wrap gap-3 items-center">
          <input
            value={topModule}
            onChange={(e) => setTopModule(e.target.value)}
            placeholder="top module (auto)"
            className="flex-1 min-w-[10rem] bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono"
          />
          <input
            value={simTime}
            onChange={(e) => setSimTime(e.target.value)}
            type="number"
            min={50}
            className="w-24 bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono"
            title="sim time (ns)"
          />
          <input
            value={clockName}
            onChange={(e) => setClockName(e.target.value)}
            className="w-20 bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono"
            title="clock name"
          />
          <input
            value={periodNs}
            onChange={(e) => setPeriodNs(e.target.value)}
            type="number"
            min={0.1}
            step={0.1}
            className="w-20 bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono"
            title="period (ns)"
          />
          <label className="font-mono text-[10px] text-slate-400 inline-flex items-center gap-1">
            <input type="checkbox" checked={skipSim || !tbFile} disabled={!tbFile} onChange={(e) => setSkipSim(e.target.checked)} />
            skip sim
          </label>
          <button onClick={run} disabled={running || !rtlIds.length} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="btn-lab-run">
            {running ? <><Loader2 size={12} className="animate-spin" /> Running</> : <><Play size={12} /> Run Lab</>}
          </button>
        </div>

        <div className="px-4 py-3 border-b border-[#1E293B] flex flex-wrap gap-4">
          {STAGE_ORDER.map((id) => {
            const st = stageState[id];
            if (!st && !running && !status) {
              return (
                <div key={id} className="flex items-center gap-1.5 font-mono text-xs text-slate-600">
                  <StageIcon state="pending" />
                  <span>{id}</span>
                </div>
              );
            }
            if (!st) return null;
            return (
              <div key={id} className={`flex items-center gap-1.5 font-mono text-xs ${activeStage === id ? "text-emerald-300" : "text-slate-300"}`}>
                <StageIcon state={st} />
                <span>{id}</span>
              </div>
            );
          })}
        </div>

        {(libertyFile || sdcFile || tbFile) && (
          <div className="px-4 py-2 border-b border-[#1E293B] font-mono text-[10px] text-slate-500">
            RTL={rtlIds.length}
            {tbFile ? ` · TB=${tbFile.original_filename}` : " · no TB (sim skipped)"}
            {libertyFile ? ` · liberty=${libertyFile.original_filename}` : " · no .lib (STA may mock)"}
            {sdcFile ? ` · sdc=${sdcFile.original_filename}` : " · SDC auto-scaffold"}
          </div>
        )}

        {results.length > 0 && (
          <div className="px-4 py-2 border-b border-[#1E293B] font-mono text-[10px] text-slate-400 space-y-0.5">
            {results.map((r) => (
              <div key={r.stage}>
                {r.stage}: {r.status}{r.note ? ` — ${r.note}` : ""}
              </div>
            ))}
          </div>
        )}

        <div className="flex-1 overflow-auto p-4 font-mono text-[11px] space-y-0.5 bg-[#070A0F]">
          {logs.length === 0 && !running && (
            <div className="text-slate-500">
              One click runs lint → simulate (if TB) → Yosys synth → OpenSTA.
              Upload a `.lib` for real timing; without it STA reports mock.
            </div>
          )}
          {logs.map((l, i) => (
            <div
              key={i}
              className={
                l.level === "error" ? "text-red-400" : l.level === "warn" ? "text-amber-400" : l.level === "success" ? "text-emerald-400" : "text-slate-300"
              }
            >
              {l.line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
