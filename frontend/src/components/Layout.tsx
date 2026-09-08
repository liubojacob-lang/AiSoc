import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth, hasRole } from "@/stores/auth";
import { useUi } from "@/stores/ui";
import { cn, fmtTime } from "@/lib/utils";
import { ToastHost } from "./ui";

const NAV = [
  { to: "/", label: "工作台", icon: "M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10", end: true, minRole: null },
  { to: "/alerts", label: "告警中心", icon: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z", minRole: null },
  { to: "/incidents", label: "事件中心", icon: "M12 6.5v5m0 3.5h.01M4 20h16a1 1 0 0 0 .9-1.6l-8-14a1 1 0 0 0-1.8 0l-8 14A1 1 0 0 0 4 20Z", minRole: null },
  { to: "/knowledge", label: "知识库", icon: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15Z", minRole: null },
  { to: "/assistant", label: "AI 助手", icon: "M8 10h.01M12 10h.01M16 10h.01M21 12a8.96 8.96 0 0 1-4.1 7.5L12 22l-4.9-2.5A8.96 8.96 0 0 1 3 12a9 9 0 1 1 18 0Z", minRole: null },
  { to: "/admin", label: "平台管理", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 1-.1 1.2l2 1.6-2 3.4-2.4-1a7.5 7.5 0 0 1-2 1.2l-.4 2.6h-4l-.4-2.6a7.5 7.5 0 0 1-2-1.2l-2.4 1-2-3.4 2-1.6a7.4 7.4 0 0 1 0-2.4l-2-1.6 2-3.4 2.4 1a7.5 7.5 0 0 1 2-1.2L10.5 2h4l.4 2.6a7.5 7.5 0 0 1 2 1.2l2.4-1 2 3.4-2 1.6c.1.4.1.8.1 1.2Z", minRole: "admin" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { toast } = useUi();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [bellOpen, setBellOpen] = useState(false);

  const { data: unread } = useQuery({
    queryKey: ["unread"],
    queryFn: () => api.get<{ unread: number }>("/api/v1/notifications/unread-count"),
    refetchInterval: 30_000,
  });
  const { data: notes } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<{ id: string; type: string; title: string; body: string; link_path: string | null; read_at: string | null; created_at: string }[]>("/api/v1/notifications"),
    enabled: bellOpen,
  });

  async function openBell() {
    setBellOpen((v) => !v);
  }
  async function markAllRead() {
    await api.post("/api/v1/notifications/read-all");
    qc.invalidateQueries({ queryKey: ["unread"] });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  return (
    <div className="flex min-h-screen">
      {/* sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-ink-700/70 bg-ink-900/90 backdrop-blur">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-sky-400 to-violet-500 text-sm font-extrabold text-white">AI</div>
          <div>
            <div className="text-sm font-bold tracking-wide text-white">AISOC</div>
            <div className="text-[10px] text-slate-500">AI 安全运营中心</div>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-1 px-3" aria-label="主导航">
          {NAV.filter((n) => !n.minRole || hasRole(user, n.minRole)).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition",
                  isActive ? "bg-gradient-to-r from-sky-500/15 to-violet-500/15 text-white border border-sky-500/30" : "text-slate-400 hover:bg-ink-800 hover:text-slate-200 border border-transparent",
                )}>
              <svg className="h-4.5 w-4.5 h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d={n.icon} />
              </svg>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-ink-700/70 p-4 text-[11px] text-slate-600">
          open-source · self-hosted
        </div>
      </aside>

      {/* main */}
      <div className="ml-56 flex min-h-screen flex-1 flex-col max-lg:ml-0">
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-ink-700/70 bg-ink-950/80 px-6 py-3 backdrop-blur">
          <div className="text-sm text-slate-400">安全运营工作台</div>
          <div className="flex items-center gap-3">
            <div className="relative">
              <button onClick={openBell} aria-label="通知"
                className="relative rounded-lg border border-ink-600 px-2.5 py-1.5 text-sm text-slate-400 hover:text-white">
                🔔
                {(unread?.unread ?? 0) > 0 && (
                  <span className="absolute -right-1.5 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                    {unread!.unread > 99 ? "99+" : unread!.unread}
                  </span>
                )}
              </button>
              {bellOpen && (
                <div className="absolute right-0 top-11 z-50 w-80 rounded-xl border border-ink-600 bg-ink-900 shadow-2xl">
                  <div className="flex items-center justify-between border-b border-ink-700 px-4 py-2.5">
                    <span className="text-xs font-medium text-slate-300">通知</span>
                    <button className="text-[11px] text-sky-400 hover:text-sky-300" onClick={markAllRead}>全部已读</button>
                  </div>
                  <div className="max-h-80 overflow-y-auto">
                    {!notes || notes.length === 0 ? (
                      <div className="px-4 py-6 text-center text-xs text-slate-600">暂无通知</div>
                    ) : (
                      notes.map((n) => (
                        <button key={n.id}
                          className={cn("block w-full border-b border-ink-700/60 px-4 py-2.5 text-left text-xs hover:bg-ink-800",
                            !n.read_at && "bg-sky-500/5")}
                          onClick={() => {
                            setBellOpen(false);
                            if (n.link_path) navigate(n.link_path);
                          }}>
                          <div className={cn("font-medium", n.read_at ? "text-slate-400" : "text-slate-200")}>{n.title}</div>
                          {n.body && <div className="mt-0.5 line-clamp-2 text-slate-500">{n.body}</div>}
                          <div className="mt-1 text-[10px] text-slate-600">{fmtTime(n.created_at)}</div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
            <button onClick={() => { useUi.getState().toggleTheme(); }} className="rounded-lg border border-ink-600 px-2.5 py-1.5 text-xs text-slate-400 hover:text-white" aria-label="切换主题">
              主题
            </button>
            {user ? (
              <div className="flex items-center gap-2.5">
                <div className="text-right">
                  <div className="text-xs font-medium text-slate-200">{user.display_name}</div>
                  <div className="text-[10px] text-slate-500">{user.roles.join(" · ")}</div>
                </div>
                <button className="btn-ghost !px-2.5 !py-1.5 text-xs"
                  onClick={async () => { await logout(); toast("info", "已退出登录"); navigate("/login"); }}>
                  退出
                </button>
              </div>
            ) : null}
          </div>
        </header>
        <main className="flex-1 p-6 max-lg:px-4">
          <Outlet />
        </main>
      </div>
      <ToastHost />
    </div>
  );
}
