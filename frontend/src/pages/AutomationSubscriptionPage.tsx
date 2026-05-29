import { Link, useParams } from "react-router-dom";
import {
  useSubscription,
  useSubscriptionNews,
  useSubscriptionTasks,
} from "../api/hooks";
import type { FetchTask } from "../types";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

function statusBadge(status: FetchTask["status"]): { label: string; cls: string } {
  switch (status) {
    case "pending":
      return { label: "排队中", cls: "bg-slate-100 text-slate-600" };
    case "running":
      return { label: "运行中", cls: "bg-blue-100 text-blue-700" };
    case "succeeded":
      return { label: "成功", cls: "bg-emerald-100 text-emerald-700" };
    case "failed":
      return { label: "失败", cls: "bg-red-100 text-red-700" };
  }
}

function durationMs(a: string | null, b: string | null): string {
  if (!a || !b) return "—";
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m${s % 60}s`;
}

export function AutomationSubscriptionPage() {
  const { id } = useParams<{ id: string }>();
  const sub = useSubscription(id);
  const news = useSubscriptionNews(id);
  const tasks = useSubscriptionTasks(id);

  if (sub.isLoading) {
    return <div className="text-slate-500">加载中…</div>;
  }
  if (sub.error) {
    return <div className="text-red-600">加载失败:{(sub.error as Error).message}</div>;
  }
  if (!sub.data) return null;

  return (
    <div className="space-y-4">
      <div>
        <Link to="/automation" className="text-sm text-slate-500 hover:underline">
          ← 返回自动化
        </Link>
        <h2 className="text-xl font-semibold mt-1">{sub.data.alias}</h2>
        <div className="text-sm text-slate-600 mt-0.5">板块:{sub.data.section}</div>
        <a
          href={sub.data.url}
          target="_blank"
          rel="noreferrer"
          className="text-sm text-blue-600 hover:underline break-all"
        >
          {sub.data.url}
        </a>
        <div className="text-xs text-slate-500 mt-1 flex gap-3">
          <span>条目数:{sub.data.item_count}</span>
          <span>上次抓取:{fmtDate(sub.data.last_refreshed_at)}</span>
          <span>自动:{sub.data.auto_enabled ? "已开启" : "已关闭"}</span>
        </div>
      </div>

      {/* news list */}
      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2">
          已抓取新闻 {news.data ? `(${news.data.length})` : ""}
        </h3>
        {news.isLoading ? (
          <div className="text-slate-500 text-sm">加载中…</div>
        ) : news.data && news.data.length > 0 ? (
          <div className="bg-white rounded-lg border border-slate-200 divide-y divide-slate-100 max-h-[50vh] overflow-y-auto">
            {news.data.map((n) => (
              <Link
                key={n.id}
                to={`/news/${n.id}?from=automation`}
                className="block px-4 py-3 hover:bg-slate-50"
              >
                <div className="font-medium text-slate-900">{n.title}</div>
                <div className="text-xs text-slate-500 mt-1 flex gap-3">
                  {n.pub_date && <span>{n.pub_date}</span>}
                  {n.source && <span>· {n.source}</span>}
                  <span className="ml-auto">抓取于 {fmtDate(n.fetched_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-slate-500 bg-white rounded-lg border border-slate-200 text-sm">
            暂无抓取记录
          </div>
        )}
      </section>

      {/* tasks list */}
      <section>
        <h3 className="text-sm font-medium text-slate-700 mb-2">
          抓取任务 {tasks.data ? `(${tasks.data.length})` : ""}
        </h3>
        {tasks.isLoading ? (
          <div className="text-slate-500 text-sm">加载中…</div>
        ) : tasks.data && tasks.data.length > 0 ? (
          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-600">
                <tr>
                  <th className="px-4 py-2">#</th>
                  <th className="px-4 py-2">状态</th>
                  <th className="px-4 py-2">来源</th>
                  <th className="px-4 py-2">入队</th>
                  <th className="px-4 py-2">耗时</th>
                  <th className="px-4 py-2">新增/抓取</th>
                  <th className="px-4 py-2">页数</th>
                  <th className="px-4 py-2">备注</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {tasks.data.map((t) => {
                  const b = statusBadge(t.status);
                  return (
                    <tr key={t.id} className="align-top">
                      <td className="px-4 py-2 text-slate-500">{t.id}</td>
                      <td className="px-4 py-2">
                        <span className={"px-1.5 py-0.5 rounded text-xs " + b.cls}>
                          {b.label}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-slate-600">
                        {t.source === "manual" ? "手动" : "自动"}
                      </td>
                      <td className="px-4 py-2 text-slate-600">{fmtDate(t.enqueued_at)}</td>
                      <td className="px-4 py-2 text-slate-600">
                        {durationMs(t.started_at, t.finished_at)}
                      </td>
                      <td className="px-4 py-2 text-slate-600">
                        {t.items_added ?? "—"} / {t.items_fetched ?? "—"}
                      </td>
                      <td className="px-4 py-2 text-slate-600">{t.pages_fetched ?? "—"}</td>
                      <td className="px-4 py-2 text-slate-600 max-w-md">
                        {t.error ? (
                          <span className="text-red-600 break-words">{t.error}</span>
                        ) : (
                          <span className="text-slate-500">{t.stop_reason ?? "—"}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12 text-slate-500 bg-white rounded-lg border border-slate-200 text-sm">
            暂无任务
          </div>
        )}
      </section>
    </div>
  );
}
