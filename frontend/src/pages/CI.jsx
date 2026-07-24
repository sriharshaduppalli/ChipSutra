import { useEffect, useState } from "react";
import { api, API, getToken } from "@/lib/api";
import { Github, Download, Copy, Check, Webhook } from "lucide-react";
import { toast } from "sonner";

export default function CI() {
  const [events, setEvents] = useState([]);
  const [copied, setCopied] = useState(false);

  const load = async () => {
    try { const { data } = await api.get("/ci/events"); setEvents(data); } catch {}
  };
  useEffect(() => { load(); }, []);

  const downloadYaml = async () => {
    const res = await fetch(`${API}/ci/github-workflow`, { headers: { Authorization: `Bearer ${getToken()}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "chipsutra.yml"; a.click();
    URL.revokeObjectURL(url);
    toast.success("Workflow downloaded");
  };

  const webhookUrl = `${API}/ci/webhook`;
  const copyWebhook = () => {
    navigator.clipboard.writeText(webhookUrl);
    setCopied(true);
    toast.success("Webhook URL copied");
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="p-8" data-testid="ci-page">
      <div className="pin-badge mb-2 inline-block">CI / CD</div>
      <h1 className="font-display text-3xl font-bold mb-1">GitHub Integration</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">Wire ChipSutra into your GitHub PR flow.</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-3">
            <Github size={18} className="text-emerald-400" />
            <div className="font-display text-lg font-medium">GitHub Actions Workflow</div>
          </div>
          <p className="font-mono text-xs text-slate-400 mb-4">Drop a ready-made workflow into your repo. It runs Verilator lint on changed files and (optionally) triggers a ChipSutra AI review.</p>
          <button onClick={downloadYaml} className="btn-neon inline-flex items-center gap-2" data-testid="ci-download">
            <Download size={14} /> Download chipsutra.yml
          </button>
          <div className="font-mono text-[10px] text-slate-500 mt-3 border-l-2 border-emerald-500/40 pl-2">
            Save at <span className="text-emerald-400">.github/workflows/chipsutra.yml</span> in your repo.
          </div>
        </div>

        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-3">
            <Webhook size={18} className="text-emerald-400" />
            <div className="font-display text-lg font-medium">Webhook Endpoint</div>
            <span className="pin-badge border-amber-500/40 text-amber-400">preview</span>
          </div>
          <p className="font-mono text-xs text-slate-400 mb-4">POST here from your CI. Full AI review worker ships next release — until then, events are queued and visible below.</p>
          <div className="flex gap-2">
            <input readOnly value={webhookUrl} className="flex-1 bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono" data-testid="ci-webhook-url" />
            <button onClick={copyWebhook} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="ci-webhook-copy">
              {copied ? <Check size={12} /> : <Copy size={12} />}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-6 card-surface p-6">
        <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Recent Events ({events.length})</div>
        {events.length === 0 ? (
          <div className="font-mono text-xs text-slate-500 text-center py-8">No CI events yet. Run the workflow to see them here.</div>
        ) : (
          <div className="space-y-1">
            {events.map(e => (
              <div key={e.id} className="border border-[#1E293B] p-3 flex items-center gap-3" data-testid={`ci-event-${e.id}`}>
                <Github size={14} className="text-emerald-400" />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs">{e.repo} #{e.pr || "-"} · <span className="text-slate-500">{e.sha?.slice(0, 7)}</span></div>
                  <div className="font-mono text-[10px] text-slate-500">{new Date(e.created_at).toLocaleString()} · {e.event}</div>
                </div>
                <span className="pin-badge">{e.status}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
