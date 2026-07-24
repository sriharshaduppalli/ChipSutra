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

    // Standalone Google OAuth: backend redirected with #gtoken=<jwt>
    const gtok = hash.match(/gtoken=([^&]+)/);
    if (gtok) {
      setToken(decodeURIComponent(gtok[1]));
      refreshMe().then((u) => {
        window.history.replaceState({}, "", "/app");
        if (u) { toast.success(`Welcome, ${u.name}`); nav("/app"); }
        else { toast.error("Sign-in failed"); nav("/login"); }
      });
      return;
    }

    // Emergent-managed: backend expects a session_id in hash
    const sess = hash.match(/session_id=([^&]+)/);
    if (!sess) { nav("/login"); return; }
    (async () => {
      try {
        const { data } = await api.post("/auth/google/session", { session_id: sess[1] });
        setToken(data.access_token);
        await refreshMe();
        toast.success(`Welcome, ${data.user.name}`);
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
