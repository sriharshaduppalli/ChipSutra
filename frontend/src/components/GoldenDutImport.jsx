import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BookOpen, Loader2, Download } from "lucide-react";
import { toast } from "sonner";

export default function GoldenDutImport({ projectId, onImported }) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState([]);
  const [note, setNote] = useState(null);
  const [selected, setSelected] = useState([]);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/golden-duts");
      setFiles(data.files || []);
      if (!(data.files || []).length) setNote("No golden DUTs are bundled with this installation.");
    } catch {
      setNote("Golden DUT library unavailable on this backend.");
    }
  }, []);

  useEffect(() => { if (open) load(); }, [open, load]);

  const toggle = (name) => {
    setSelected((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]));
  };

  const importGolden = async (names) => {
    setImporting(true);
    try {
      const { data } = await api.post(`/projects/${projectId}/import-golden`, names ? { names } : {});
      toast.success(`Imported ${data.count} golden file(s)`);
      setSelected([]);
      if (onImported) onImported();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail) setNote(detail);
      else toast.error("Golden DUT import failed");
    }
    setImporting(false);
  };

  return (
    <div className="mt-3 border-t border-[#1E293B] pt-3" data-testid="golden-dut-import">
      <button onClick={() => setOpen((v) => !v)} className="w-full font-mono text-[10px] uppercase tracking-widest text-slate-400 hover:text-emerald-400 inline-flex items-center gap-1" data-testid="golden-toggle">
        <BookOpen size={11} /> Golden DUTs {open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="mt-2 space-y-1">
          <div className="font-mono text-[10px] text-slate-500">Known-good reference RTL + testbenches to smoke-test the flows.</div>
          {note && <div className="font-mono text-[10px] text-amber-400/90">{note}</div>}
          {files.map((f) => (
            <label key={f.name} className="flex items-start gap-2 p-1 hover:bg-[#1A212D] cursor-pointer" data-testid={`golden-${f.name}`}>
              <input type="checkbox" checked={selected.includes(f.name)} onChange={() => toggle(f.name)} className="mt-1" />
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[11px] truncate">{f.name}</span>
                <span className="block font-mono text-[10px] text-slate-500">{(f.bytes / 1024).toFixed(1)} KB · {f.kind}{f.description ? ` · ${f.description}` : ""}</span>
              </span>
            </label>
          ))}
          <div className="flex gap-2 pt-1">
            <button onClick={() => importGolden(selected)} disabled={importing || !selected.length} className="btn-outline-neon text-[10px] inline-flex items-center gap-1 disabled:opacity-40" data-testid="golden-import-selected">
              {importing ? <Loader2 size={10} className="animate-spin" /> : <Download size={10} />} Import selected
            </button>
            <button onClick={() => importGolden(null)} disabled={importing || !files.length} className="btn-outline-neon text-[10px] inline-flex items-center gap-1 disabled:opacity-40" data-testid="golden-import-all">
              <Download size={10} /> Import all RTL/TB
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
