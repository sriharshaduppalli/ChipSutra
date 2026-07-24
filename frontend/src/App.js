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
    <AuthProvider>
      <BrowserRouter>
        <Toaster theme="dark" position="bottom-right" toastOptions={{ style: { background: "#121721", border: "1px solid #1E293B", color: "#F8FAFC", fontFamily: "JetBrains Mono, monospace" } }} />
        <AppRouter />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
