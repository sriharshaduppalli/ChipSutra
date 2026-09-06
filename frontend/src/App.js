import React from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "sonner";
import Landing from "@/pages/Landing";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import DashboardLayout from "@/pages/DashboardLayout";
import Projects from "@/pages/Projects";
import ProjectDetail from "@/pages/ProjectDetail";
import Coverage from "@/pages/Coverage";
import Waveform from "@/pages/Waveform";
import Reports from "@/pages/Reports";
import Templates from "@/pages/Templates";
import Docs from "@/pages/Docs";
import AuthCallback from "@/pages/AuthCallback";
import Workspaces from "@/pages/Workspaces";
import CI from "@/pages/CI";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      const msg = String(this.state.error?.message || this.state.error);
      const apiDown = /network|ECONNREFUSED|Failed to fetch|ERR_CONNECTION/i.test(msg);
      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100 p-8">
          <div className="max-w-lg font-mono text-sm space-y-3">
            <div className="text-rose-400 text-base">Something went wrong</div>
            <p className="text-slate-400">
              {apiDown
                ? "Backend looks unreachable. Start ChipSutra with scripts/start-chipsutra.ps1 and confirm http://localhost:8001/api/health."
                : msg}
            </p>
            <button
              type="button"
              className="px-3 py-1.5 border border-slate-600 rounded hover:bg-slate-900"
              onClick={() => window.location.assign("/app")}
            >
              Reload workspace
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="min-h-screen flex items-center justify-center text-slate-400 font-mono text-sm">Loading verification workspace...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppRouter() {
  const location = useLocation();
  // Synchronously handle OAuth callback (hash contains session_id or gtoken) BEFORE rendering protected routes
  if (location.hash?.includes("session_id=") || location.hash?.includes("gtoken=")) {
    return <AuthCallback />;
  }
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/docs" element={<Docs />} />
      <Route path="/app" element={<Protected><DashboardLayout /></Protected>}>
        <Route index element={<Projects />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:pid" element={<ProjectDetail />} />
        <Route path="coverage" element={<Coverage />} />
        <Route path="waveform" element={<Waveform />} />
        <Route path="templates" element={<Templates />} />
        <Route path="workspaces" element={<Workspaces />} />
        <Route path="ci" element={<CI />} />
        <Route path="reports" element={<Reports />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        {/* PUBLIC_URL is "" on the custom domain and "/ChipSutra" on the
            github.io project URL, so routing works from either origin. */}
        <BrowserRouter basename={process.env.PUBLIC_URL || undefined}>
          <Toaster theme="dark" position="bottom-right" toastOptions={{ style: { background: "#121721", border: "1px solid #1E293B", color: "#F8FAFC", fontFamily: "JetBrains Mono, monospace" } }} />
          <AppRouter />
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  );
}

export default App;
