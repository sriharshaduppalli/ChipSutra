import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
const googleSignIn = () => {
  const redirectUrl = window.location.origin + "/app";
  window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
};

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const { login } = useAuth();
  const nav = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email, password);
      toast.success("Signed in");
      nav("/app");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Login failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid-bg flex items-center justify-center p-6">
      <div className="w-full max-w-md card-surface p-8 relative">
        <div className="absolute top-0 left-0 right-0 h-px bg-emerald-500"></div>
        <Link to="/" className="font-mono text-xs uppercase tracking-widest text-slate-400 hover:text-emerald-400" data-testid="back-home">← chipsutra</Link>
        <h1 className="font-display text-3xl font-bold mt-6 mb-2">Sign in</h1>
        <p className="font-mono text-xs text-slate-400 mb-6">Access your verification workspace.</p>

        <button type="button" onClick={googleSignIn} className="w-full border border-[#1E293B] bg-[#0B0E14] hover:border-emerald-500/50 py-2.5 font-mono text-sm text-slate-200 inline-flex items-center justify-center gap-2 mb-4" data-testid="google-signin">
          <svg width="16" height="16" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.1 8 3l5.7-5.7C33.6 6.1 29 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.9 1.1 8 3l5.7-5.7C33.6 6.1 29 4 24 4 16.3 4 9.6 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5 0 9.5-1.9 12.9-5.1l-6-5.1C29.1 35.3 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.6 5.1C9.4 39.5 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.3-4.1 5.8l6 5.1C40.5 35.8 44 30.5 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>
          Continue with Google
        </button>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-[#1E293B]"></div>
          <span className="font-mono text-[10px] text-slate-500 uppercase">or</span>
          <div className="flex-1 h-px bg-[#1E293B]"></div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <input type="email" required placeholder="email" value={email} onChange={e=>setEmail(e.target.value)} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="login-email" />
          <input type="password" required placeholder="password" value={password} onChange={e=>setPassword(e.target.value)} className="w-full bg-[#0B0E14] border border-[#1E293B] px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-emerald-500" data-testid="login-password" />
          <button disabled={busy} className="btn-neon w-full" data-testid="login-submit">{busy ? "Signing in..." : "Sign In →"}</button>
        </form>
        <div className="mt-6 text-xs font-mono text-slate-400 text-center">
          No account? <Link to="/signup" className="text-emerald-400 hover:underline" data-testid="link-signup">Create workspace</Link>
        </div>
      </div>
    </div>
  );
}
