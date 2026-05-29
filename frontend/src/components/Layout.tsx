import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import clsx from "clsx";

export function Layout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  // 路由切换自动关闭抽屉
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex flex-col h-full">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-4">
          <h1 className="text-lg font-bold text-slate-900">daily-news</h1>
          {/* 桌面 nav */}
          <nav className="hidden md:flex gap-1 ml-4">
            <Tab to="/new">新建订阅</Tab>
            <Tab to="/subscriptions">订阅管理</Tab>
            <Tab to="/automation">自动化</Tab>
            <Tab to="/timeline">时间线</Tab>
          </nav>
          {/* 移动端汉堡 */}
          <button
            type="button"
            aria-label="打开菜单"
            onClick={() => setDrawerOpen(true)}
            className="md:hidden ml-auto inline-flex items-center justify-center min-h-[44px] min-w-[44px] rounded-md text-slate-700 hover:bg-slate-100"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        </div>
      </header>

      {/* 抽屉 */}
      <div
        className={clsx(
          "md:hidden fixed inset-0 z-50 transition-opacity",
          drawerOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
        aria-hidden={!drawerOpen}
      >
        {/* 遮罩 */}
        <div
          className="absolute inset-0 bg-black/40"
          onClick={() => setDrawerOpen(false)}
        />
        {/* 面板 */}
        <aside
          className={clsx(
            "absolute right-0 top-0 h-full w-72 max-w-[80%] bg-white shadow-xl transition-transform duration-200 flex flex-col",
            drawerOpen ? "translate-x-0" : "translate-x-full",
          )}
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200">
            <span className="text-base font-semibold text-slate-900">菜单</span>
            <button
              type="button"
              aria-label="关闭菜单"
              onClick={() => setDrawerOpen(false)}
              className="inline-flex items-center justify-center min-h-[44px] min-w-[44px] rounded-md text-slate-600 hover:bg-slate-100"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          <nav className="flex flex-col p-2 gap-1">
            <DrawerTab to="/new">新建订阅</DrawerTab>
            <DrawerTab to="/subscriptions">订阅管理</DrawerTab>
            <DrawerTab to="/automation">自动化</DrawerTab>
            <DrawerTab to="/timeline">时间线</DrawerTab>
          </nav>
        </aside>
      </div>

      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-4 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Tab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          "px-3 py-1.5 rounded-md text-sm font-medium",
          isActive
            ? "bg-blue-100 text-blue-700"
            : "text-slate-600 hover:bg-slate-100",
        )
      }
    >
      {children}
    </NavLink>
  );
}

function DrawerTab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          "block px-4 py-3 rounded-md text-base font-medium",
          isActive
            ? "bg-blue-100 text-blue-700"
            : "text-slate-700 hover:bg-slate-100",
        )
      }
    >
      {children}
    </NavLink>
  );
}
