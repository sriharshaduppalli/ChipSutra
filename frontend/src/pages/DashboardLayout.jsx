import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { FolderGit2, Waves, Activity, FileText, LogOut, Cpu, LayoutTemplate, BookOpen, Users, Github } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import NotificationsBell from "@/components/NotificationsBell";

const NAV = [
  { to: "/app/projects", label: "Projects", icon: FolderGit2, testid: "nav-projects" },
  { to: "/app/workspaces", label: "Workspaces", icon: Users, testid: "nav-workspaces" },
  { to: "/app/templates", label: "Templates", icon: LayoutTemplate, testid: "nav-templates" },
  { to: "/app/coverage", label: "Coverage", icon: Activity, testid: "nav-coverage" },
  { to: "/app/waveform", label: "Waveform", icon: Waves, testid: "nav-waveform" },
  { to: "/app/reports", label: "Reports", icon: FileText, testid: "nav-reports" },
  { to: "/app/ci", label: "CI / GitHub", icon: Github, testid: "nav-ci" },
];

export default function DashboardLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();

  const doLogout = () => { logout(); nav("/"); };

  return (
    <div className="min-h-screen flex text-slate-100">
      <aside className="w-56 border-r border-[#1E293B] bg-[#0B0E14] flex flex-col shrink-0" data-testid="sidebar">
        <div className="h-16 border-b border-[#1E293B] flex items-center px-4 gap-2">
          <Cpu size={18} className="text-emerald-400" />
          <span className="font-display font-bold tracking-tight">Chip<span className="text-emerald-400">Sutra</span></span>
          <div className="ml-auto"><NotificationsBell /></div>
        </div>
        <nav className="flex-1 py-4">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.testid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-2.5 text-sm font-mono border-l-2 ${isActive ? 'border-emerald-500 text-emerald-400 bg-[#121721]' : 'border-transparent text-slate-400 hover:text-slate-100 hover:bg-[#121721]/60'}`
              }
            >
              <n.icon size={16} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-[#1E293B] p-4">
          <div className="font-mono text-xs text-slate-400 mb-2 truncate" data-testid="sidebar-user-email">{user?.email}</div>
          <a href="/docs" target="_blank" rel="noreferrer" className="w-full flex items-center gap-2 text-xs font-mono text-slate-400 hover:text-emerald-400 mb-2" data-testid="sidebar-docs">
            <BookOpen size={14} /> Docs
          </a>
          <button onClick={doLogout} className="w-full flex items-center gap-2 text-xs font-mono text-slate-400 hover:text-red-400 mb-3" data-testid="sidebar-logout">
            <LogOut size={14} /> Sign out
          </button>
          <div className="pt-3 border-t border-[#1E293B]">
            <a href="https://github.com/sriharshaduppalli/ChipSutra" target="_blank" rel="noreferrer" className="font-mono text-[10px] text-slate-500 hover:text-emerald-400 block" data-testid="sidebar-attribution">
              Powered by ChipSutra™ →
            </a>
            <div className="font-mono text-[9px] text-slate-600 mt-1">© 2026 Sri Harsha Duppalli</div>
          </div>
        </div>
      </aside>
      <main className="flex-1 min-w-0">
        <Outlet />
      </main>
    </div>
  );
}
