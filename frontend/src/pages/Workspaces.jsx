import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Plus, Users, Activity, X, Crown, Cpu } from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";

export default function Workspaces() {
  const [items, setItems] = useState([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [activity, setActivity] = useState([]);
  const [projects, setProjects] = useState([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");

  const load = async () => {
    const { data } = await api.get("/workspaces");
    setItems(data);
  };
  useEffect(() => { load(); }, []);

  const loadDetail = async (wid) => {
    setSelected(wid);
    const [d, a, p] = await Promise.all([
      api.get(`/workspaces/${wid}`),
      api.get(`/workspaces/${wid}/activity`),
      api.get(`/workspaces/${wid}/projects`),
    ]);
    setDetail(d.data);
    setActivity(a.data);
    setProjects(p.data);
  };

  const create = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    try {
      await api.post("/workspaces", form);
      toast.success("Workspace created");
      setCreating(false);
      setForm({ name: "", description: "" });
      load();
    } catch { toast.error("Failed"); }
  };

  const invite = async (e) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    try {
      await api.post(`/workspaces/${selected}/members`, { email: inviteEmail, role: inviteRole });
      toast.success("Member invited");
      setInviteEmail("");
      loadDetail(selected);
      load();
    } catch (err) { toast.error(err.response?.data?.detail || "Failed"); }
  };

  const removeMember = async (uid) => {
    try {
      await api.delete(`/workspaces/${selected}/members/${uid}`);
      toast.success("Removed");
      loadDetail(selected);
    } catch { toast.error("Failed"); }
  };

  return (
    <div className="p-8" data-testid="workspaces-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="pin-badge mb-2 inline-block">TEAM</div>
          <h1 className="font-display text-3xl font-bold">Workspaces</h1>
          <p className="font-mono text-xs text-slate-400 mt-1">Group projects, invite teammates, and audit activity.</p>
        </div>
        <button onClick={() => setCreating(true)} className="btn-neon inline-flex items-center gap-2" data-testid="new-ws-btn">
          <Plus size={16} /> New Workspace
        </button>
      </div>

      {creating && (
        <form onSubmit={create} className="card-surface p-6 mb-6 space-y-3" data-testid="new-ws-form">
          <input required placeholder="workspace name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="nw-name" />
          <input placeholder="description (optional)" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="nw-desc" />
          <div className="flex gap-2">
            <button className="btn-neon" data-testid="nw-submit">Create</button>
            <button type="button" onClick={() => setCreating(false)} className="btn-outline-neon" data-testid="nw-cancel">Cancel</button>
          </div>
        </form>
      )}

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-4 space-y-2">
          {items.length === 0 ? (
            <div className="card-surface p-8 text-center">
              <Users size={32} className="mx-auto mb-3 text-slate-600" />
              <div className="font-display text-lg mb-1">No workspaces</div>
              <div className="font-mono text-xs text-slate-400">Create one to invite teammates.</div>
            </div>
          ) : items.map(w => (
            <button key={w.id} onClick={() => loadDetail(w.id)} className={`w-full text-left card-surface p-4 ${selected === w.id ? 'border-emerald-500/60' : ''}`} data-testid={`ws-${w.id}`}>
              <div className="flex items-center justify-between mb-1">
                <div className="font-display text-base font-medium">{w.name}</div>
                {w.is_owner && <Crown size={12} className="text-amber-400" />}
              </div>
              <div className="font-mono text-[10px] text-slate-400">{w.project_count || 0} projects · {(w.members?.length || 0) + 1} people</div>
            </button>
          ))}
        </div>

        <div className="col-span-12 md:col-span-8 card-surface p-6">
          {!detail ? (
            <div className="font-mono text-xs text-slate-500 text-center py-16">Select a workspace to view members and activity.</div>
          ) : (
            <>
              <div className="flex items-start justify-between mb-6">
                <div>
                  <div className="pin-badge mb-2 inline-block">{detail.current_role?.toUpperCase()}</div>
                  <h2 className="font-display text-2xl font-bold">{detail.name}</h2>
                  <div className="font-mono text-xs text-slate-400">{detail.description || "—"}</div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="pin-badge">Seat: {(detail.members?.length || 0) + 1} / {detail.seat_limit}</div>
                  {detail.current_role === "owner" && (
                    <button onClick={async () => {
                      if (!window.confirm(`Delete workspace "${detail.name}"? Projects will be unlinked (not deleted).`)) return;
                      try {
                        await api.delete(`/workspaces/${detail.id}`);
                        toast.success("Workspace deleted");
                        setDetail(null); setSelected(null); load();
                      } catch { toast.error("Failed"); }
                    }} className="text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-500/60 px-2 py-1 text-[10px] font-mono uppercase tracking-widest" data-testid="ws-delete">
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {(detail.current_role === "owner" || detail.current_role === "admin") && (
                <form onSubmit={invite} className="flex gap-2 mb-6" data-testid="ws-invite-form">
                  <input type="email" required placeholder="member@email.com" value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} className="flex-1 bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="ws-invite-email" />
                  <select value={inviteRole} onChange={e => setInviteRole(e.target.value)} className="bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono" data-testid="ws-invite-role">
                    <option value="admin">admin</option>
                    <option value="member">member</option>
                  </select>
                  <button className="btn-neon text-xs" data-testid="ws-invite-submit">Invite</button>
                </form>
              )}

              <div className="mb-6">
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">Members ({(detail.members?.length || 0) + 1})</div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2 p-2 border border-[#1E293B]">
                    <Crown size={12} className="text-amber-400" />
                    <div className="font-mono text-xs flex-1">{detail.owner_email}</div>
                    <span className="pin-badge">owner</span>
                  </div>
                  {(detail.members || []).map(m => (
                    <div key={m.user_id} className="flex items-center gap-2 p-2 border border-[#1E293B]" data-testid={`ws-member-${m.user_id}`}>
                      <div className="w-5 h-5 bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center font-mono text-[10px] text-emerald-400">{(m.name || m.email)[0]?.toUpperCase()}</div>
                      <div className="font-mono text-xs flex-1">{m.name || m.email}</div>
                      <span className="pin-badge">{m.role}</span>
                      {(detail.current_role === "owner" || detail.current_role === "admin") && (
                        <button onClick={() => removeMember(m.user_id)} className="text-slate-500 hover:text-red-400" data-testid={`ws-rm-${m.user_id}`}><X size={12} /></button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="mb-6">
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">Projects ({projects.length})</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {projects.map(p => (
                    <Link to={`/app/projects/${p.id}`} key={p.id} className="border border-[#1E293B] hover:border-emerald-500/40 p-3" data-testid={`ws-proj-${p.id}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <Cpu size={12} className="text-emerald-400" />
                        <div className="font-mono text-xs">{p.name}</div>
                      </div>
                      <div className="font-mono text-[10px] text-slate-500">{p.design_type} · {p.language}</div>
                    </Link>
                  ))}
                  {projects.length === 0 && <div className="col-span-2 font-mono text-[11px] text-slate-500 text-center py-4">No projects. Create one and assign it to this workspace.</div>}
                </div>
              </div>

              <div>
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2 flex items-center gap-1"><Activity size={12} /> Activity Log</div>
                <div className="max-h-[300px] overflow-y-auto space-y-1">
                  {activity.map(a => (
                    <div key={a.id} className="border-l-2 border-emerald-500/40 pl-3 py-1 font-mono text-[11px]" data-testid={`activity-${a.id}`}>
                      <span className="text-emerald-400">{a.actor_name}</span> <span className="text-slate-400">{a.action}</span> <span className="text-slate-300">{a.target_name}</span>
                      <div className="text-[9px] text-slate-500">{new Date(a.created_at).toLocaleString()}</div>
                    </div>
                  ))}
                  {activity.length === 0 && <div className="font-mono text-[10px] text-slate-500 text-center py-4">No activity yet.</div>}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
