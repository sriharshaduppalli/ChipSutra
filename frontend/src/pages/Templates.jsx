import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Cpu, Copy, Check } from "lucide-react";
import { toast } from "sonner";

export default function Templates() {
  const [templates, setTemplates] = useState([]);
  const [copied, setCopied] = useState(null);

  useEffect(() => {
    api.get("/templates").then(r => setTemplates(r.data));
  }, []);

  const copy = (t) => {
    navigator.clipboard.writeText(t.prompt_seed);
    setCopied(t.id);
    toast.success("Prompt copied — paste it in a project's Generate panel");
    setTimeout(() => setCopied(null), 1500);
  };

  const byCat = templates.reduce((acc, t) => {
    acc[t.category] = acc[t.category] || [];
    acc[t.category].push(t);
    return acc;
  }, {});

  return (
    <div className="p-8" data-testid="templates-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="pin-badge mb-2 inline-block">GALLERY</div>
          <h1 className="font-display text-3xl font-bold">Chiplet & IP Templates</h1>
          <p className="font-mono text-xs text-slate-400 mt-1">Pre-baked verification patterns for UCIe, BoW, and multi-chiplet designs. Copy a prompt and use it in any project.</p>
        </div>
      </div>

      {Object.entries(byCat).map(([cat, list]) => (
        <div key={cat} className="mb-8">
          <div className="flex items-center gap-3 mb-3">
            <div className="pin-badge border-emerald-500/40 text-emerald-400">{cat}</div>
            <div className="divider-glow flex-1"></div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {list.map(t => (
              <div key={t.id} className="card-surface neon-border p-5" data-testid={`template-${t.id}`}>
                <div className="flex items-center justify-between mb-3">
                  <Cpu size={16} className="text-emerald-400" />
                  <button onClick={() => copy(t)} className="text-xs font-mono text-emerald-400 hover:underline inline-flex items-center gap-1" data-testid={`template-copy-${t.id}`}>
                    {copied === t.id ? <><Check size={12} /> copied</> : <><Copy size={12} /> copy prompt</>}
                  </button>
                </div>
                <div className="font-display text-lg font-medium mb-2">{t.name}</div>
                <div className="font-mono text-[11px] text-slate-400 leading-relaxed mb-3 min-h-[3.5rem]">{t.description}</div>
                <div className="flex flex-wrap gap-1 mb-3">
                  {t.tags.map(tg => <span key={tg} className="pin-badge text-[9px]">{tg}</span>)}
                </div>
                <div className="border-t border-[#1E293B] pt-3">
                  <div className="font-mono text-[10px] text-slate-500 mb-1">Recommended modules</div>
                  <div className="flex flex-wrap gap-1">
                    {t.modules.map(m => <span key={m} className="pin-badge text-[9px] text-emerald-400 border-emerald-500/40">{m}</span>)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      <div className="mt-8 card-surface p-6 text-center">
        <div className="font-mono text-xs text-slate-400 mb-2">Missing a template you need?</div>
        <Link to="/#contact" className="btn-outline-neon inline-block" data-testid="templates-request">Request a template →</Link>
      </div>
    </div>
  );
}
