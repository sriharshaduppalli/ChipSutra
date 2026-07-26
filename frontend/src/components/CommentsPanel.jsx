import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { MessageSquare, Trash2 } from "lucide-react";
import { toast } from "sonner";

export default function CommentsPanel({ generationId, currentUserId }) {
  const [comments, setComments] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/generations/${generationId}/comments`);
      setComments(data);
    } catch {}
  }, [generationId]);

  useEffect(() => { if (generationId) load(); }, [generationId, load]);

  const submit = async (e) => {
    e.preventDefault();
    if (!text.trim() || !generationId) return;
    setBusy(true);
    try {
      await api.post(`/generations/${generationId}/comments`, { text });
      setText("");
      load();
    } catch { toast.error("Failed to post comment"); }
    setBusy(false);
  };

  const del = async (id) => {
    try { await api.delete(`/comments/${id}`); load(); }
    catch { toast.error("Failed"); }
  };

  if (!generationId) return null;

  return (
    <div className="border-t border-[#1E293B] p-3" data-testid="comments-panel">
      <div className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-slate-400 mb-2">
        <MessageSquare size={11} /> Comments ({comments.length})
      </div>
      <div className="space-y-2 max-h-[160px] overflow-y-auto mb-2">
        {comments.map(c => (
          <div key={c.id} className="border-l-2 border-emerald-500/40 pl-2 group" data-testid={`comment-${c.id}`}>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-[10px] text-emerald-400">{c.user_name}</span>
              <span className="font-mono text-[9px] text-slate-500">{new Date(c.created_at).toLocaleString()}</span>
              {c.user_id === currentUserId && (
                <button onClick={() => del(c.id)} className="ml-auto opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400" data-testid={`comment-del-${c.id}`}><Trash2 size={10} /></button>
              )}
            </div>
            <div className="font-mono text-[11px] text-slate-300 whitespace-pre-wrap">{c.text}</div>
          </div>
        ))}
        {comments.length === 0 && <div className="font-mono text-[10px] text-slate-500 text-center py-2">No comments yet.</div>}
      </div>
      <form onSubmit={submit} className="flex gap-2" data-testid="comment-form">
        <input value={text} onChange={e => setText(e.target.value)} placeholder="Add a comment..." className="flex-1 bg-[#0B0E14] border border-[#1E293B] px-2 py-1 text-[11px] font-mono focus:outline-none focus:border-emerald-500" data-testid="comment-input" />
        <button disabled={busy} className="btn-outline-neon text-[11px] px-3 py-1" data-testid="comment-submit">Post</button>
      </form>
    </div>
  );
}
