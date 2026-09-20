import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "画廊", icon: "▦", end: true },
  { to: "/unbookmarked", label: "已取消", icon: "☆", end: false },
  { to: "/tasks", label: "任务", icon: "⟳", end: false },
  { to: "/stats", label: "统计", icon: "◔", end: false },
  { to: "/export", label: "导出", icon: "⇩", end: false },
  { to: "/settings", label: "设置", icon: "⚙", end: false },
];

export default function AppLayout() {
  return (
    <div className="flex h-full">
      <aside className="hidden w-[168px] shrink-0 flex-col border-r border-border-subtle bg-surface-raised p-2 md:flex">
        <div className="px-2 py-3 text-sm font-semibold tracking-wide">Pixiv Archive</div>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                [
                  "flex items-center gap-2 rounded-md px-2.5 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-surface-hover text-text-primary"
                    : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
                ].join(" ")
              }
            >
              <span aria-hidden>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto pb-14 md:pb-0">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border-subtle bg-surface-raised md:hidden">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              [
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px]",
                isActive ? "text-text-primary" : "text-text-muted",
              ].join(" ")
            }
          >
            <span aria-hidden>{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
