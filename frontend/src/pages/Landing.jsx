import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { motion } from "framer-motion";
import { Cpu, Zap, Activity, GitBranch, FileCode, Waves, Shield, LayoutGrid, ArrowRight, CheckCircle2, Cog, Puzzle, Network, Layers } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

const ChipSutraMark = () => (
  <div className="flex items-center gap-2" data-testid="chipsutra-logo">
    <div className="w-7 h-7 border border-emerald-500/60 relative">
      <div className="absolute inset-1 bg-emerald-500/20"></div>
      <div className="absolute -left-1 top-2 w-1 h-0.5 bg-emerald-500"></div>
      <div className="absolute -left-1 bottom-2 w-1 h-0.5 bg-emerald-500"></div>
      <div className="absolute -right-1 top-2 w-1 h-0.5 bg-emerald-500"></div>
      <div className="absolute -right-1 bottom-2 w-1 h-0.5 bg-emerald-500"></div>
    </div>
    <span className="font-display font-bold text-lg tracking-tight text-slate-50">Chip<span className="text-emerald-400">Sutra</span></span>
  </div>
);

const Nav = () => (
  <header className="sticky top-0 z-40 backdrop-blur-md bg-[#0B0E14]/80 border-b border-[#1E293B]">
    <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
      <Link to="/" className="flex items-center gap-2"><ChipSutraMark /></Link>
      <nav className="hidden md:flex items-center gap-8 font-mono text-xs uppercase tracking-widest text-slate-400">
        <a href="#features" className="hover:text-emerald-400" data-testid="nav-features">Modules</a>
        <a href="#usecases" className="hover:text-emerald-400" data-testid="nav-usecases">Use Cases</a>
        <a href="#languages" className="hover:text-emerald-400" data-testid="nav-langs">Languages</a>
        <a href="#pricing" className="hover:text-emerald-400" data-testid="nav-pricing">Pricing</a>
        <Link to="/docs" className="hover:text-emerald-400" data-testid="nav-docs">Docs</Link>
        <a href="#waitlist" className="hover:text-emerald-400" data-testid="nav-waitlist">Waitlist</a>
      </nav>
      <div className="flex items-center gap-3">
        <Link to="/login" className="text-sm font-mono text-slate-300 hover:text-emerald-400" data-testid="nav-login">Sign in</Link>
        <Link to="/signup" className="btn-neon text-xs" data-testid="nav-signup">Launch Workspace →</Link>
      </div>
    </div>
  </header>
);

const modules = [
  { icon: FileCode, title: "Testbench Generation", desc: "Scalable, reusable UVM/SV testbenches with error injection hooks, drivers, monitors, scoreboards.", tag: "SV / UVM" },
  { icon: Shield, title: "SVA Assertion Gen", desc: "Protocol, safety and liveness assertions synthesized from spec + RTL context.", tag: "SVA" },
  { icon: Activity, title: "Coverage Analysis", desc: "Parse coverage DB / reports, surface holes, generate closure tests.", tag: "COV" },
  { icon: Waves, title: "Waveform Viewer", desc: "In-browser VCD parser with WaveDrom-style timing diagrams and summary reports.", tag: "VCD" },
  { icon: GitBranch, title: "Spec ↔ RTL", desc: "Bi-directional: generate RTL from spec, or extract a spec from existing RTL.", tag: "S↔R" },
  { icon: Cog, title: "Debug Analysis", desc: "Paste sim log — get ranked root-cause hypotheses and next debug steps.", tag: "DBG" },
];

const usecases = [
  { icon: Cpu, k: "Block", d: "Function block verification for ALU, FIFO, controllers." },
  { icon: Puzzle, k: "IP", d: "Verification IP for reusable soft/hard cores." },
  { icon: LayoutGrid, k: "Subsystem", d: "Cluster-level verification with integrated protocols." },
  { icon: Layers, k: "SoC", d: "System-on-chip full verification and integration." },
  { icon: Network, k: "Chiplet / Multi-chiplet", d: "UCIe, BoW interconnect verification templates." },
];

const languages = ["Verilog", "SystemVerilog", "VHDL", "UVM", "SVA", "Chisel-friendly"];

const tiers = [
  { name: "Free", price: "$0", period: "/mo", features: ["Up to 3 projects", "Claude Sonnet 4.5", "Community support"], cta: "Join waitlist", highlight: false },
  { name: "Pro", price: "$49", period: "/mo", features: ["Unlimited projects", "Claude + GPT-5.2 switcher", "Coverage + Waveform tools", "Priority support"], cta: "Get early access", highlight: true },
  { name: "Enterprise", price: "Custom", period: "", features: ["On-prem deploy option", "SSO / Team collab", "Fine-tuned domain LLM", "Dedicated engineer"], cta: "Contact sales", highlight: false },
];

const Feature = ({ icon: Icon, title, desc, tag, idx }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true }}
    transition={{ duration: 0.4, delay: idx * 0.05 }}
    className="card-surface neon-border p-6 relative"
    data-testid={`feature-${title.toLowerCase().replace(/\W+/g,'-')}`}
  >
    <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-emerald-500/0 via-emerald-500/60 to-emerald-500/0"></div>
    <div className="flex items-start justify-between mb-4">
      <Icon size={22} className="text-emerald-400" />
      <span className="pin-badge">{tag}</span>
    </div>
    <h3 className="font-display text-lg font-medium text-slate-50 mb-2">{title}</h3>
    <p className="text-sm text-slate-400 font-mono leading-relaxed">{desc}</p>
  </motion.div>
);

export default function Landing() {
  const [wl, setWl] = useState({ email: "", name: "", company: "", role: "", tier: "Pro" });
  const [contact, setContact] = useState({ name: "", email: "", message: "" });
  const navigate = useNavigate();

  const submitWaitlist = async (e) => {
    e.preventDefault();
    try {
      await api.post("/waitlist", wl);
      toast.success("You're on the waitlist. We'll be in touch.");
      setWl({ email: "", name: "", company: "", role: "", tier: "Pro" });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Something went wrong");
    }
  };

  const submitContact = async (e) => {
    e.preventDefault();
    try {
      await api.post("/contact", contact);
      toast.success("Message sent. We'll reach out shortly.");
      setContact({ name: "", email: "", message: "" });
    } catch (err) {
      toast.error("Failed to send message");
    }
  };

  return (
    <div className="min-h-screen text-slate-100">
      <Nav />

      {/* HERO */}
      <section className="relative overflow-hidden" data-testid="hero-section">
        <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none"></div>
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-[#0B0E14] pointer-events-none"></div>
        <div
          className="absolute inset-0 opacity-20 mix-blend-screen pointer-events-none"
          style={{ backgroundImage: "url('https://images.pexels.com/photos/28215391/pexels-photo-28215391.jpeg')", backgroundSize: "cover", backgroundPosition: "center" }}
        ></div>

        <div className="relative max-w-7xl mx-auto px-6 pt-24 pb-28">
          <div className="flex items-center gap-3 mb-8">
            <span className="pin-badge text-emerald-400 border-emerald-500/40">MADE IN INDIA · AI × EDA</span>
            <span className="font-mono text-xs text-slate-500 uppercase tracking-widest">v0.1 · Early Access</span>
          </div>
          <h1 className="font-display text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight max-w-5xl leading-[1.05]">
            Silicon-grade <span className="text-emerald-400">verification</span>,
            <br />automated from spec to <span className="ion-text">coverage closure</span>.
          </h1>
          <p className="mt-8 text-lg font-mono text-slate-400 max-w-2xl leading-relaxed">
            ChipSutra generates UVM testbenches, SVA assertions, covergroups, testplans and debug hints for
            Verilog / SystemVerilog / VHDL blocks, IPs, SoCs and chiplets — powered by Claude Sonnet 4.5 and GPT-5.2.
          </p>
          <div className="mt-10 flex flex-wrap gap-4 items-center">
            <Link to="/signup" className="btn-neon inline-flex items-center gap-2" data-testid="hero-cta-signup">
              Launch Workspace <ArrowRight size={16} />
            </Link>
            <a href="#waitlist" className="btn-outline-neon" data-testid="hero-cta-waitlist">Join Waitlist</a>
            <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
              <div className="w-2 h-2 bg-emerald-500 animate-pulse"></div>
              <span>LLM online · Claude Sonnet 4.5 + GPT-5.2</span>
            </div>
          </div>

          {/* Terminal preview */}
          <div className="mt-16 card-surface p-6 max-w-3xl font-mono text-xs relative scanline">
            <div className="flex items-center gap-2 mb-4 text-slate-500">
              <span className="w-2 h-2 bg-emerald-500"></span>
              <span className="w-2 h-2 bg-amber-500"></span>
              <span className="w-2 h-2 bg-slate-600"></span>
              <span className="ml-3 text-slate-400">chipsutra ~ verification workspace</span>
            </div>
            <div className="space-y-1 text-slate-300">
              <div><span className="text-emerald-400">$</span> chipsutra generate --module testbench --lang systemverilog</div>
              <div className="text-slate-500">→ parsing rtl/uart_top.sv ...</div>
              <div className="text-slate-500">→ synthesizing UVM env: driver, monitor, scoreboard ...</div>
              <div className="text-emerald-400">✓ testbench.sv (412 lines) — coverage plan attached</div>
              <div><span className="text-emerald-400">$</span> chipsutra analyze --coverage cov.rpt <span className="cli-caret"></span></div>
            </div>
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section id="features" className="relative py-24" data-testid="features-section">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex items-end justify-between mb-12 flex-wrap gap-4">
            <div>
              <div className="pin-badge mb-4 inline-block">01 · MODULES</div>
              <h2 className="font-display text-4xl font-bold tracking-tight max-w-2xl">Six AI-powered engines. One verification workspace.</h2>
            </div>
            <p className="text-sm font-mono text-slate-400 max-w-md">Iterate spec → RTL → tests → coverage in one loop. Every artifact is downloadable, versioned, and diff-able.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {modules.map((m, i) => <Feature key={m.title} idx={i} {...m} />)}
          </div>
        </div>
      </section>

      {/* USE CASES */}
      <section id="usecases" className="py-24 relative border-t border-[#1E293B]" data-testid="usecases-section">
        <div className="max-w-7xl mx-auto px-6">
          <div className="pin-badge mb-4 inline-block">02 · SCOPE</div>
          <h2 className="font-display text-4xl font-bold tracking-tight mb-12">From single blocks to multi-chiplet packages.</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-0 border border-[#1E293B]">
            {usecases.map((u, i) => (
              <div key={u.k} className={`p-6 ${i !== usecases.length - 1 ? 'border-b md:border-b-0 md:border-r border-[#1E293B]' : ''} bg-[#121721] hover:bg-[#1A212D] transition-colors`} data-testid={`usecase-${u.k.toLowerCase()}`}>
                <u.icon size={20} className="text-emerald-400 mb-4" />
                <div className="font-display text-lg font-medium mb-1">{u.k}</div>
                <div className="text-xs font-mono text-slate-400 leading-relaxed">{u.d}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* LANGUAGES */}
      <section id="languages" className="py-24 border-t border-[#1E293B]" data-testid="languages-section">
        <div className="max-w-7xl mx-auto px-6">
          <div className="pin-badge mb-4 inline-block">03 · LANGUAGES</div>
          <h2 className="font-display text-4xl font-bold tracking-tight mb-12">Speak every HDL your team writes.</h2>
          <div className="flex flex-wrap gap-3">
            {languages.map((l) => (
              <div key={l} className="pin-badge text-sm px-4 py-2 border-emerald-500/30 text-emerald-300" data-testid={`lang-${l.toLowerCase()}`}>{l}</div>
            ))}
          </div>
        </div>
      </section>

      {/* PRICING */}
      <section id="pricing" className="py-24 border-t border-[#1E293B]" data-testid="pricing-section">
        <div className="max-w-7xl mx-auto px-6">
          <div className="pin-badge mb-4 inline-block">04 · PRICING</div>
          <h2 className="font-display text-4xl font-bold tracking-tight mb-4">Simple tiers. Made for engineers.</h2>
          <p className="font-mono text-sm text-slate-400 mb-12 max-w-lg">Start free, scale with your team, deploy on-prem when you need it.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {tiers.map((t) => (
              <div key={t.name} className={`card-surface p-8 relative ${t.highlight ? 'border-emerald-500/60' : ''}`} data-testid={`tier-${t.name.toLowerCase()}`}>
                {t.highlight && <div className="absolute -top-px left-0 right-0 h-px bg-emerald-400"></div>}
                {t.highlight && <div className="absolute top-4 right-4 pin-badge border-emerald-500/50 text-emerald-400">POPULAR</div>}
                <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">{t.name}</div>
                <div className="flex items-baseline gap-1 mb-6">
                  <span className="font-display text-5xl font-bold">{t.price}</span>
                  <span className="font-mono text-sm text-slate-500">{t.period}</span>
                </div>
                <ul className="space-y-3 mb-8">
                  {t.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm font-mono text-slate-300"><CheckCircle2 size={14} className="text-emerald-400 mt-0.5 flex-shrink-0" />{f}</li>
                  ))}
                </ul>
                <a href="#waitlist" className={t.highlight ? "btn-neon w-full inline-block text-center" : "btn-outline-neon w-full inline-block text-center"} data-testid={`tier-cta-${t.name.toLowerCase()}`}>{t.cta}</a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* WAITLIST */}
      <section id="waitlist" className="py-24 border-t border-[#1E293B] relative" data-testid="waitlist-section">
        <div className="absolute inset-0 dot-bg opacity-30 pointer-events-none"></div>
        <div className="max-w-3xl mx-auto px-6 relative">
          <div className="pin-badge mb-4 inline-block">05 · JOIN</div>
          <h2 className="font-display text-4xl font-bold tracking-tight mb-4">Get early access to ChipSutra.</h2>
          <p className="font-mono text-sm text-slate-400 mb-8">First 500 engineers get 3 months of Pro free. Priority for semiconductor companies and research labs.</p>
          <form onSubmit={submitWaitlist} className="card-surface p-6 space-y-4" data-testid="waitlist-form">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <input required type="email" placeholder="work email *" value={wl.email} onChange={(e)=>setWl({...wl, email: e.target.value})} className="bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="waitlist-email" />
              <input placeholder="name" value={wl.name} onChange={(e)=>setWl({...wl, name: e.target.value})} className="bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="waitlist-name" />
              <input placeholder="company / org" value={wl.company} onChange={(e)=>setWl({...wl, company: e.target.value})} className="bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="waitlist-company" />
              <select value={wl.tier} onChange={(e)=>setWl({...wl, tier: e.target.value})} className="bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="waitlist-tier">
                <option>Free</option><option>Pro</option><option>Enterprise</option>
              </select>
            </div>
            <button type="submit" className="btn-neon w-full" data-testid="waitlist-submit">Reserve My Seat →</button>
          </form>
        </div>
      </section>

      {/* CONTACT / ABOUT */}
      <section id="contact" className="py-24 border-t border-[#1E293B]">
        <div className="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-2 gap-12">
          <div>
            <div className="pin-badge mb-4 inline-block">06 · ABOUT</div>
            <h2 className="font-display text-3xl font-bold tracking-tight mb-4">Built by verification engineers, for verification engineers.</h2>
            <p className="font-mono text-sm text-slate-400 leading-relaxed">
              ChipSutra is a Made-in-India EDA startup building the AI copilot the semiconductor industry has been waiting for.
              We believe every verification engineer deserves a partner that can read specs, write testbenches, chase coverage
              holes, and reason about failing waveforms — while they focus on architecture.
            </p>
            <div className="mt-8 grid grid-cols-3 gap-4">
              <div className="border-l border-emerald-500/50 pl-3">
                <div className="font-display text-3xl font-bold text-emerald-400">9</div>
                <div className="font-mono text-xs uppercase text-slate-400">AI Modules</div>
              </div>
              <div className="border-l border-emerald-500/50 pl-3">
                <div className="font-display text-3xl font-bold text-emerald-400">2</div>
                <div className="font-mono text-xs uppercase text-slate-400">Frontier LLMs</div>
              </div>
              <div className="border-l border-emerald-500/50 pl-3">
                <div className="font-display text-3xl font-bold text-emerald-400">∞</div>
                <div className="font-mono text-xs uppercase text-slate-400">Iterations</div>
              </div>
            </div>
          </div>
          <form onSubmit={submitContact} className="card-surface p-6 space-y-4" data-testid="contact-form">
            <div className="font-mono text-xs uppercase tracking-widest text-slate-400 mb-2">Contact us</div>
            <input required placeholder="name" value={contact.name} onChange={(e)=>setContact({...contact, name: e.target.value})} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="contact-name" />
            <input required type="email" placeholder="email" value={contact.email} onChange={(e)=>setContact({...contact, email: e.target.value})} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="contact-email" />
            <textarea required rows={5} placeholder="how can we help?" value={contact.message} onChange={(e)=>setContact({...contact, message: e.target.value})} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500 resize-none" data-testid="contact-message" />
            <button type="submit" className="btn-outline-neon w-full" data-testid="contact-submit">Send Message</button>
          </form>
        </div>
      </section>

      <footer className="border-t border-[#1E293B] py-8">
        <div className="max-w-7xl mx-auto px-6 flex flex-wrap items-center justify-between gap-4 font-mono text-xs text-slate-500">
          <ChipSutraMark />
          <div>© 2026 ChipSutra · Made in India · verification@chipsutra.ai</div>
        </div>
      </footer>
    </div>
  );
}
