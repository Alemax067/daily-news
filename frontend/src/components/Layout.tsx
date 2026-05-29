import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";

export function Layout() {
  return (
    <div className="flex flex-col h-full">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-4">
          <h1 className="text-lg font-bold text-slate-900">daily-news</h1>
          <nav className="flex gap-1 ml-4">
            <Tab to="/new">新建订阅</Tab>
            <Tab to="/subscriptions">订阅管理</Tab>
            <Tab to="/automation">自动化</Tab>
            <Tab to="/timeline">时间线</Tab>
          </nav>
        </div>
      </header>
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
