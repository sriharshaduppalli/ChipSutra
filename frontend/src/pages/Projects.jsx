import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Cpu, FileCode2, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

const DESIGN_TYPES = [
  { value: "block", label: "Block" },
  { value: "ip", label: "IP" },
  { value: "subsystem", label: "Subsystem" },
  { value: "soc", label: "SoC" },
  { value: "chiplet", label: "Chiplet" },
  { value: "multi-chiplet", label: "Multi-Chiplet" },
];
const LANGS = ["systemverilog", "verilog", "vhdl", "uvm"];

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", design_type: "block", language: "systemverilog", workspace_id: "" });

  const load = async () => {
    try {
      const [pr, ws] = await Promise.all([api.get("/projects"), api.get("/workspaces")]);
      setProjects(pr.data);
      setWorkspaces(ws.data);
    } catch (err) {
      toast.error("Failed to load projects");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    try {
      const payload = { ...form, workspace_id: form.workspace_id || null };
      await api.post("/projects", payload);
      toast.success("Project created");
      setCreating(false);
      setForm({ name: "", description: "", design_type: "block", language: "systemverilog", workspace_id: "" });
      load();
    } catch (err) { toast.error("Failed to create project"); }
  };

  const del = async (pid) => {
    if (!window.confirm("Delete this project?")) return;
    try { await api.delete(`/projects/${pid}`); toast.success("Deleted"); load(); }
    catch { toast.error("Failed to delete"); }
  };

  return (
    <div className="p-8" data-testid="projects-page">
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="pin-badge mb-2 inline-block">WORKSPACE</div>
          <h1 className="font-display text-3xl font-bold">Projects</h1>
          <p className="font-mono text-xs text-slate-400 mt-1">Verify blocks, IPs, subsystems, SoCs and chiplets.</p>
        </div>
        <button onClick={() => setCreating(true)} className="btn-neon inline-flex items-center gap-2" data-testid="new-project-btn">
          <Plus size={16} /> New Project
        </button>
      </div>

      {creating && (
        <form onSubmit={create} className="card-surface p-6 mb-6 space-y-3" data-testid="new-project-form">
          <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">New Project</div>
          <input required placeholder="project name" value={form.name} onChange={e=>setForm({...form, name: e.target.value})} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="np-name" />
          <input placeholder="description (optional)" value={form.description} onChange={e=>setForm({...form, description: e.target.value})} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="np-desc" />
          <div className="grid grid-cols-2 gap-3">
            <select value={form.design_type} onChange={e=>setForm({...form, design_type: e.target.value})} className="bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="np-type">
              {DESIGN_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <select value={form.language} onChange={e=>setForm({...form, language: e.target.value})} className="bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="np-lang">
              {LANGS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          {workspaces.length > 0 && (
            <select value={form.workspace_id} onChange={e=>setForm({...form, workspace_id: e.target.value})} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="np-ws">
              <option value="">— Personal (no workspace) —</option>
              {workspaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          )}
          <div className="flex gap-2">
            <button className="btn-neon" data-testid="np-submit">Create</button>
            <button type="button" onClick={() => setCreating(false)} className="btn-outline-neon" data-testid="np-cancel">Cancel</button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="font-mono text-sm text-slate-400">Loading...</div>
      ) : projects.length === 0 ? (
        <div className="card-surface p-16 text-center">
          <Cpu size={40} className="mx-auto mb-4 text-slate-600" />
          <div className="font-display text-xl mb-2">No projects yet</div>
          <div className="font-mono text-xs text-slate-400">Create your first verification project to begin.</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <div key={p.id} className="card-surface neon-border p-5 relative group" data-testid={`project-card-${p.id}`}>
              <div className="flex items-start justify-between mb-3">
                <FileCode2 size={18} className="text-emerald-400" />
                <div className="flex gap-2">
                  <span className="pin-badge uppercase">{p.design_type}</span>
                  <span className="pin-badge uppercase text-slate-400">{p.language}</span>
                </div>
              </div>
              <Link to={`/app/projects/${p.id}`} className="block">
                <div className="font-display text-lg font-medium mb-1 group-hover:text-emerald-400 transition-colors">{p.name}</div>
                <div className="font-mono text-xs text-slate-400 line-clamp-2 min-h-[2rem]">{p.description || "No description"}</div>
                <div className="font-mono text-[10px] text-slate-500 mt-3">Created {new Date(p.created_at).toLocaleDateString()}</div>
              </Link>
              <button onClick={() => del(p.id)} className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-opacity" data-testid={`project-delete-${p.id}`}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
