import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, setToken } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function AuthCallback() {
  const location = useLocation();
  const nav = useNavigate();
  const { refreshMe } = useAuth();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;
    const hash = location.hash || window.location.hash;
    const m = hash.match(/session_id=([^&]+)/);
    if (!m) { nav("/login"); return; }
    const session_id = m[1];
    (async () => {
      try {
        const { data } = await api.post("/auth/google/session", { session_id });
        setToken(data.access_token);
        await refreshMe();
        toast.success(`Welcome, ${data.user.name}`);
        // Clear hash
        window.history.replaceState({}, "", "/app");
        nav("/app");
      } catch (err) {
        toast.error(err.response?.data?.detail || "Google sign-in failed");
        nav("/login");
      }
    })();
  }, [location.hash, nav, refreshMe]);

  return (
    <div className="min-h-screen flex items-center justify-center text-slate-400 font-mono text-sm">
      Signing you in with Google...
    </div>
  );
}
