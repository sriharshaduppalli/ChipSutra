import { Link } from "react-router-dom";
import { BookOpen, FileCode, Cpu, Waves, Activity, ArrowRight } from "lucide-react";

const SECTIONS = [
  {
    icon: FileCode,
    title: "Getting Started",
    testid: "docs-getting-started",
    body: [
      "1. Sign up with email or Google. You land on the Projects workspace.",
      "2. Create a project — pick a design type (Block / IP / Subsystem / SoC / Chiplet).",
      "3. Upload your RTL (.v / .sv / .vhd) and/or spec docs (.md / .pdf / .txt).",
      "4. Open the project, select files, pick an AI module, hit Generate.",
    ]
  },
  {
    icon: Cpu,
    title: "AI Generation Modules",
    testid: "docs-modules",
    body: [
      "UVM Testbench — scalable env with driver / monitor / scoreboard.",
      "SVA Assertions — protocol, safety, and liveness properties.",
      "Checkers — reference model + protocol / functional checkers.",
      "Covergroups — bins, cross coverage, illegal_bins.",
      "Spec → RTL / RTL → Spec — bi-directional conversion.",
      "Testplan / Coverage-Hole Tests / Debug Analysis.",
      "Formal Hints — SVA properties for SymbiYosys proofs.",
      "Model: ChipSutra-VLSI 3B runs locally by default; Claude and GPT appear in the switcher only if you configure API keys.",
    ]
  },
  {
    icon: Activity,
    title: "Coverage Analysis",
    testid: "docs-coverage",
    body: [
      "Navigate to Coverage. Upload a text/RPT/LOG with lines like `Statement coverage: 87.5%`.",
      "You'll get an overall heatmap, per-metric breakdown, and a ranked list of holes.",
      "Feed those holes to the Coverage-Hole Tests module in any project to auto-generate closure tests.",
    ]
  },
  {
    icon: Waves,
    title: "Waveform (VCD)",
    testid: "docs-waveform",
    body: [
      "Upload a .vcd file on the Waveform page.",
      "We render up to 32 signals × 200 time steps in a WaveDrom-style SVG timing diagram.",
      "Single-bit signals show clean transitions; multi-bit signals show bus values per step.",
    ]
  },
  {
    icon: FileCode,
    title: "Verilator Simulation",
    testid: "docs-verilator",
    body: [
      "In a project, select .v/.sv files then click 'Simulate' (Verilator).",
      "We run `verilator --lint-only` on your selected sources and stream logs live.",
      "If Verilator is unavailable in your deployment, we fall back to a mock flow that still demonstrates the pipeline.",
      "Coming soon: full compile + run with waveform capture.",
    ]
  },
  {
    icon: Cpu,
    title: "Team Collaboration",
    testid: "docs-collab",
    body: [
      "Open a project → click 'Share'.",
      "Invite by ChipSutra email address. Editor role: full edit access. Viewer: read-only.",
      "Every generation supports threaded comments so your team can review artifacts together.",
    ]
  },
];

const CHANGELOG = [
  { date: "2026-02", title: "v0.2 — Collaboration + Verilator + Chiplet Templates", items: ["Team invites with editor/viewer roles", "Generation comments", "Real Verilator (--lint-only) integration with mock fallback", "UCIe / BoW / Chiplet templates gallery", "Google Sign-in via Emergent Auth"] },
  { date: "2026-02", title: "v0.1 — MVP", items: ["9 AI generation modules (Testbench, SVA, Checkers, Covergroups, Spec↔RTL, Testplan, Coverage-Hole Tests, Debug)", "Claude Sonnet 4.5 + GPT-5.2 switcher", "Coverage parser + heatmap", "VCD waveform viewer"] },
];

export default function Docs() {
  return (
    <div className="min-h-screen text-slate-100">
      <header className="sticky top-0 z-40 backdrop-blur-md bg-[#0B0E14]/80 border-b border-[#1E293B]">
        <div className="max-w-5xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 font-display font-bold" data-testid="docs-home">Chip<span className="text-emerald-400">Sutra</span> <span className="pin-badge ml-2">DOCS</span></Link>
          <div className="flex gap-4 font-mono text-xs">
            <a href="#getting-started" className="text-slate-400 hover:text-emerald-400">Guide</a>
            <a href="#changelog" className="text-slate-400 hover:text-emerald-400">Changelog</a>
            <Link to="/app" className="text-emerald-400" data-testid="docs-app-link">Open App →</Link>
          </div>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-6 py-12">
        <div className="pin-badge mb-4 inline-block">DOCUMENTATION</div>
        <h1 className="font-display text-4xl font-bold mb-2">ChipSutra Guide</h1>
        <p className="font-mono text-sm text-slate-400 mb-10 max-w-2xl">Everything you need to spin up a verification workspace, generate testbenches, chase coverage, and collaborate with your team.</p>

        <div id="getting-started" className="space-y-8">
          {SECTIONS.map(s => (
            <section key={s.title} className="card-surface p-6" data-testid={s.testid}>
              <div className="flex items-center gap-3 mb-4">
                <s.icon size={20} className="text-emerald-400" />
                <h2 className="font-display text-2xl font-bold">{s.title}</h2>
              </div>
              <ul className="space-y-2">
                {s.body.map((b, i) => (
                  <li key={i} className="font-mono text-sm text-slate-300 leading-relaxed border-l-2 border-emerald-500/30 pl-3">{b}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <div id="changelog" className="mt-16">
          <div className="pin-badge mb-2 inline-block">CHANGELOG</div>
          <h2 className="font-display text-3xl font-bold mb-6">What's shipped</h2>
          <div className="space-y-4">
            {CHANGELOG.map((c, idx) => (
              <div key={idx} className="card-surface p-5" data-testid={`changelog-${idx}`}>
                <div className="flex items-baseline gap-3 mb-3">
                  <div className="font-mono text-[10px] text-slate-500">{c.date}</div>
                  <div className="font-display text-lg font-medium">{c.title}</div>
                </div>
                <ul className="space-y-1">
                  {c.items.map((it, i) => <li key={i} className="font-mono text-xs text-slate-300"><span className="text-emerald-400">→</span> {it}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-16 card-surface p-6 text-center">
          <div className="font-display text-2xl font-bold mb-2">Ready to verify silicon-grade?</div>
          <Link to="/signup" className="btn-neon inline-flex items-center gap-2" data-testid="docs-signup">Launch Workspace <ArrowRight size={14} /></Link>
        </div>

        <footer className="mt-12 pt-6 border-t border-[#1E293B] font-mono text-xs text-slate-500 text-center">
          © 2026 ChipSutra · verification@chipsutra.ai · Made in India
        </footer>
      </main>
    </div>
  );
}
