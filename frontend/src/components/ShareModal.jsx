import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { UserPlus, X, Users, Crown } from "lucide-react";
import { toast } from "sonner";

export default function ShareModal({ project, onClose, onUpdate }) {
  const [collabs, setCollabs] = useState(project.collaborators || []);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("editor");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/projects/${project.id}/collaborators`);
      setCollabs(data);
    } catch {}
  }, [project.id]);

  useEffect(() => { load(); }, [load]);

  const invite = async (e) => {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    try {
      await api.post(`/projects/${project.id}/collaborators`, { email, role });
      toast.success(`Invited ${email}`);
      setEmail("");
      load();
      onUpdate && onUpdate();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Invite failed");
    } finally { setBusy(false); }
  };

  const remove = async (uid) => {
    try {
      await api.delete(`/projects/${project.id}/collaborators/${uid}`);
      toast.success("Removed");
      load();
      onUpdate && onUpdate();
    } catch { toast.error("Failed to remove"); }
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="share-modal">
      <div className="card-surface w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="border-b border-[#1E293B] px-5 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users size={16} className="text-emerald-400" />
            <div className="font-mono text-sm">Share · {project.name}</div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100" data-testid="share-close"><X size={16} /></button>
        </div>
        <div className="p-5 space-y-4">
          {project.is_owner && (
            <form onSubmit={invite} className="flex gap-2" data-testid="invite-form">
              <input type="email" required placeholder="collaborator@email.com" value={email} onChange={e => setEmail(e.target.value)} className="flex-1 bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="invite-email" />
              <select value={role} onChange={e => setRole(e.target.value)} className="bg-[#0B0E14] border border-[#1E293B] px-2 text-xs font-mono focus:outline-none focus:border-emerald-500" data-testid="invite-role">
                <option value="editor">editor</option>
                <option value="viewer">viewer</option>
              </select>
              <button disabled={busy} className="btn-neon text-xs inline-flex items-center gap-1" data-testid="invite-submit"><UserPlus size={12} /> Invite</button>
            </form>
          )}
          <div>
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">People with access</div>
            <div className="space-y-1">
              <div className="flex items-center gap-3 p-2 border border-[#1E293B]" data-testid="collab-owner">
                <Crown size={14} className="text-amber-400" />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs truncate">Owner</div>
                  <div className="font-mono text-[10px] text-slate-500">Full access · owner</div>
                </div>
              </div>
              {collabs.map(c => (
                <div key={c.user_id} className="flex items-center gap-3 p-2 border border-[#1E293B]" data-testid={`collab-${c.user_id}`}>
                  <div className="w-6 h-6 bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center font-mono text-xs text-emerald-400">{(c.name || c.email || "?")[0]?.toUpperCase()}</div>
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs truncate">{c.name || c.email}</div>
                    <div className="font-mono text-[10px] text-slate-500">{c.email} · {c.role}</div>
                  </div>
                  {project.is_owner && (
                    <button onClick={() => remove(c.user_id)} className="text-slate-500 hover:text-red-400" data-testid={`collab-remove-${c.user_id}`}><X size={12} /></button>
                  )}
                </div>
              ))}
              {collabs.length === 0 && <div className="font-mono text-[10px] text-slate-500 text-center py-4">No collaborators yet.</div>}
            </div>
          </div>
          <div className="font-mono text-[10px] text-slate-500 border-l-2 border-emerald-500/40 pl-2">
            Collaborators must have a ChipSutra account (email/password or Google). Invite them to sign up first.
          </div>
        </div>
      </div>
    </div>
  );
}
