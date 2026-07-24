import { useEffect, useState } from "react";
import { api } from "@/lib/api";

// Detects Google auth mode from backend /health.
// Returns {mode: "emergent" | "standalone" | "disabled", loading, onClick}
export default function useGoogleAuth() {
  const [mode, setMode] = useState("loading");
  useEffect(() => {
    api.get("/health").then(r => setMode(r.data?.google_auth || "disabled")).catch(() => setMode("disabled"));
  }, []);

  const onClick = async () => {
    if (mode === "emergent") {
      const redirectUrl = window.location.origin + "/app";
      window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
      return;
    }
    if (mode === "standalone") {
      try {
        const { data } = await api.get("/auth/google/url");
        window.location.href = data.url;
      } catch (err) {
        alert("Google sign-in unavailable: " + (err.response?.data?.detail || err.message));
      }
      return;
    }
  };

  return { mode, loading: mode === "loading", onClick, enabled: mode === "emergent" || mode === "standalone" };
}
