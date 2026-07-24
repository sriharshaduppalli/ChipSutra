import { useEffect, useState, useRef } from "react";
import { api } from "@/lib/api";
import { Bell, Check } from "lucide-react";
import { Link } from "react-router-dom";

export default function NotificationsBell() {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef();

  const load = async () => {
    try {
      const { data } = await api.get("/notifications");
      setItems(data.items || []);
      setUnread(data.unread || 0);
    } catch {}
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const markAll = async () => {
    await api.post("/notifications/read-all");
    load();
  };

  const markOne = async (id) => {
    await api.post(`/notifications/${id}/read`);
    load();
  };

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="relative text-slate-400 hover:text-emerald-400" data-testid="bell-btn">
        <Bell size={16} />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-emerald-500 text-[9px] font-mono text-black flex items-center justify-center" data-testid="bell-count">{unread > 9 ? "9+" : unread}</span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-8 w-80 card-surface z-50 shadow-2xl" data-testid="bell-dropdown">
          <div className="border-b border-[#1E293B] px-4 py-2 flex items-center justify-between">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400">Notifications</div>
            {unread > 0 && <button onClick={markAll} className="text-[10px] font-mono text-emerald-400 hover:underline" data-testid="bell-mark-all">mark all read</button>}
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            {items.length === 0 ? (
              <div className="p-6 text-center font-mono text-xs text-slate-500">No notifications yet.</div>
            ) : items.map(n => (
              <div key={n.id} onClick={() => markOne(n.id)} className={`px-4 py-3 border-b border-[#1E293B] cursor-pointer hover:bg-[#1A212D] ${!n.read ? 'bg-emerald-500/[0.03]' : ''}`} data-testid={`notif-${n.id}`}>
                <div className="flex items-start gap-2">
                  {!n.read && <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full mt-1.5 flex-shrink-0"></div>}
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs">{n.title}</div>
                    {n.body && <div className="font-mono text-[10px] text-slate-400 mt-0.5">{n.body}</div>}
                    <div className="flex items-center justify-between mt-1">
                      <div className="font-mono text-[9px] text-slate-500">{new Date(n.created_at).toLocaleString()}</div>
                      {n.link && <Link to={n.link} className="font-mono text-[10px] text-emerald-400 hover:underline">open →</Link>}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
