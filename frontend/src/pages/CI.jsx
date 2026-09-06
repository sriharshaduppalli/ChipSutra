import { useEffect, useState } from "react";
import { api, API, getToken } from "@/lib/api";
import { Github, Download, Copy, Check, Webhook } from "lucide-react";
import { toast } from "sonner";

export default function CI() {
  const [events, setEvents] = useState([]);
  const [copied, setCopied] = useState(false);
  const [diff, setDiff] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [pasteReview, setPasteReview] = useState(null);

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

  const reviewPaste = async () => {
    if (!diff.trim()) return toast.error("Paste a unified git diff first");
    setReviewing(true);
    setPasteReview(null);
    try {
      const { data } = await api.post("/ci/review-diff", { repo: "local", diff });
      setPasteReview(data);
      toast.success(data.ok ? "Review PASS" : "Needs attention");
      load();
    } catch {
      toast.error("Review failed");
    }
    setReviewing(false);
  };

  const findingsOf = (e) => e?.review?.findings || e?.findings || [];

  return (
    <div className="p-8" data-testid="ci-page">
      <div className="pin-badge mb-2 inline-block">CI / CD</div>
      <h1 className="font-display text-3xl font-bold mb-1">GitHub Integration</h1>
      <p className="font-mono text-xs text-slate-400 mb-6">PR diff → Verilator lint + ChipSutra classify. Not vendor sign-off.</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card-surface p-6">
          <div className="flex items-center gap-2 mb-3">
            <Github size={18} className="text-emerald-400" />
            <div className="font-display text-lg font-medium">GitHub Actions Workflow</div>
          </div>
          <p className="font-mono text-xs text-slate-400 mb-4">Drop a ready-made workflow into your repo. It lints changed HDL and posts the unified diff to ChipSutra for a review comment when <span className="text-emerald-400">CHIPSUTRA_TOKEN</span> is set.</p>
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
          </div>
          <p className="font-mono text-xs text-slate-400 mb-4">POST a JSON body with <span className="text-emerald-400">diff</span> (unified). Optional <span className="text-emerald-400">comment: true</span> posts to the PR when <span className="text-emerald-400">GITHUB_TOKEN</span> is set on the backend.</p>
          <div className="flex gap-2">
            <input readOnly value={webhookUrl} className="flex-1 bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono" data-testid="ci-webhook-url" />
            <button onClick={copyWebhook} className="btn-outline-neon text-xs inline-flex items-center gap-1" data-testid="ci-webhook-copy">
              {copied ? <Check size={12} /> : <Copy size={12} />}
            </button>
          </div>
        </div>
      </div>

      <div className="mt-6 card-surface p-6">
        <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Paste unified diff (no GitHub)</div>
        <textarea
          value={diff}
          onChange={(e) => setDiff(e.target.value)}
          placeholder={"diff --git a/dut.sv b/dut.sv\n..."}
          className="w-full h-36 bg-[#0B0E14] border border-[#1E293B] px-3 py-2 text-xs font-mono text-slate-200"
          data-testid="ci-diff-paste"
        />
        <button onClick={reviewPaste} disabled={reviewing} className="btn-neon mt-3 text-xs" data-testid="ci-review-paste">
          {reviewing ? "Reviewing…" : "Review diff"}
        </button>
        {pasteReview && (
          <div className="mt-3 font-mono text-[11px] text-slate-300" data-testid="ci-paste-result">
            <div className={pasteReview.ok ? "text-emerald-400" : "text-amber-400"}>
              {pasteReview.ok ? "PASS" : "NEEDS ATTENTION"} · {(pasteReview.files || []).join(", ") || "no HDL files"}
            </div>
            {(pasteReview.findings || []).map((f, i) => (
              <div key={i} className="mt-1 text-slate-400">- {f.title}: {f.hint}</div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-6 card-surface p-6">
        <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-3">Recent Events ({events.length})</div>
        {events.length === 0 ? (
          <div className="font-mono text-xs text-slate-500 text-center py-8">No CI events yet. Paste a diff or run the workflow.</div>
        ) : (
          <div className="space-y-1">
            {events.map(e => (
              <div key={e.id} className="border border-[#1E293B] p-3" data-testid={`ci-event-${e.id}`}>
                <div className="flex items-center gap-3">
                  <Github size={14} className="text-emerald-400" />
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs">{e.repo} #{e.pr || "-"} · <span className="text-slate-500">{e.sha?.slice(0, 7)}</span></div>
                    <div className="font-mono text-[10px] text-slate-500">{new Date(e.created_at).toLocaleString()} · {e.event}</div>
                  </div>
                  <span className="pin-badge">{e.status}</span>
                </div>
                {findingsOf(e).length > 0 && (
                  <div className="mt-2 font-mono text-[10px] text-slate-400 space-y-0.5">
                    {findingsOf(e).slice(0, 4).map((f, i) => (
                      <div key={i}>{f.title} ({f.severity})</div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
