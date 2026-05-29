import { Link, useNavigate } from "react-router-dom";
import {
  useDeleteSubscription,
  useRefreshPreview,
  useSubscriptions,
} from "../api/hooks";
import { Button } from "../components/Button";
import type { Subscription } from "../types";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function SubscriptionsPage() {
  const { data, isLoading, error } = useSubscriptions();
  const refresh = useRefreshPreview();
  const del = useDeleteSubscription();
  const navigate = useNavigate();

  if (isLoading) return <div className="text-slate-500">加载中…</div>;
  if (error) return <div className="text-red-600">加载失败:{(error as Error).message}</div>;
  if (!data || data.length === 0) {
    return (
      <div className="text-center py-12 text-slate-500">
        <p>暂无订阅</p>
        <p className="mt-2">
          去
          <Link to="/new" className="text-blue-600 hover:underline mx-1">
            新建订阅
          </Link>
          创建第一个吧
        </p>
      </div>
    );
  }

  const handleRefresh = (id: string) =>
    refresh.mutate(id, {
      onSuccess: (r) => alert(`已抓取 ${r.fetched} 条到预览`),
      onError: (e) => alert("刷新失败:" + (e as Error).message),
    });

  const handleDelete = (s: Subscription) => {
    if (confirm(`删除订阅「${s.alias}」及其所有新闻?`)) {
      del.mutate(s.id);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1">
        <h2 className="text-xl font-semibold">订阅管理 ({data.length})</h2>
        <p className="text-xs text-slate-500">
          这里的「刷新」抓最新 5 条到预览;自动化抓取在
          <Link to="/automation" className="text-blue-600 hover:underline mx-1">
            自动化
          </Link>
          页设置
        </p>
      </div>

      {/* 桌面 table */}
      <div className="hidden md:block bg-white rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-2">别名</th>
              <th className="px-4 py-2">板块</th>
              <th className="px-4 py-2">URL</th>
              <th className="px-4 py-2">预览条目</th>
              <th className="px-4 py-2">上次预览刷新</th>
              <th className="px-4 py-2 w-44 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((s) => (
              <tr
                key={s.id}
                className="hover:bg-slate-50 cursor-pointer"
                onClick={() => navigate(`/subscriptions/${s.id}`)}
              >
                <td className="px-4 py-3 font-medium">{s.alias}</td>
                <td className="px-4 py-3 text-slate-600">{s.section}</td>
                <td className="px-4 py-3 text-slate-600 max-w-xs truncate">
                  {s.url}
                </td>
                <td className="px-4 py-3">{s.preview_item_count}</td>
                <td className="px-4 py-3 text-slate-600">
                  {fmtDate(s.preview_refreshed_at)}
                </td>
                <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                  <Button
                    size="sm"
                    variant="secondary"
                    className="mr-2"
                    disabled={refresh.isPending && refresh.variables === s.id}
                    onClick={() => handleRefresh(s.id)}
                  >
                    {refresh.isPending && refresh.variables === s.id ? "刷新中…" : "刷新"}
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => handleDelete(s)}>
                    删除
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 移动卡片 */}
      <div className="md:hidden space-y-3">
        {data.map((s) => (
          <div
            key={s.id}
            className="bg-white rounded-lg border border-slate-200 p-4 active:bg-slate-50"
            onClick={() => navigate(`/subscriptions/${s.id}`)}
          >
            <div className="font-medium text-slate-900">{s.alias}</div>
            <div className="text-sm text-slate-600 mt-0.5">板块:{s.section}</div>
            <div className="text-xs text-slate-500 mt-1 truncate">{s.url}</div>
            <div className="text-xs text-slate-500 mt-2 flex flex-wrap gap-x-3 gap-y-0.5">
              <span>预览 {s.preview_item_count} 条</span>
              <span>· 上次刷新 {fmtDate(s.preview_refreshed_at)}</span>
            </div>
            <div
              className="mt-3 flex gap-2"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                variant="secondary"
                className="flex-1"
                disabled={refresh.isPending && refresh.variables === s.id}
                onClick={() => handleRefresh(s.id)}
              >
                {refresh.isPending && refresh.variables === s.id ? "刷新中…" : "刷新"}
              </Button>
              <Button
                variant="danger"
                className="flex-1"
                onClick={() => handleDelete(s)}
              >
                删除
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
