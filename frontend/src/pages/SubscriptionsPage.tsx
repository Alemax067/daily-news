import { Link, useNavigate } from "react-router-dom";
import {
  useDeleteSubscription,
  useRefreshSubscription,
  useSubscriptions,
} from "../api/hooks";
import { Button } from "../components/Button";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function SubscriptionsPage() {
  const { data, isLoading, error } = useSubscriptions();
  const refresh = useRefreshSubscription();
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

  return (
    <div className="space-y-3">
      <h2 className="text-xl font-semibold">已有订阅 ({data.length})</h2>
      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-2">别名</th>
              <th className="px-4 py-2">板块</th>
              <th className="px-4 py-2">URL</th>
              <th className="px-4 py-2">条目</th>
              <th className="px-4 py-2">上次刷新</th>
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
                <td className="px-4 py-3">{s.item_count}</td>
                <td className="px-4 py-3 text-slate-600">
                  {fmtDate(s.last_refreshed_at)}
                </td>
                <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                  <Button
                    variant="secondary"
                    className="mr-2"
                    disabled={refresh.isPending && refresh.variables === s.id}
                    onClick={() =>
                      refresh.mutate(s.id, {
                        onSuccess: (r) =>
                          alert(`已抓取 ${r.fetched} 条,新增 ${r.added} 条`),
                        onError: (e) => alert("刷新失败:" + (e as Error).message),
                      })
                    }
                  >
                    {refresh.isPending && refresh.variables === s.id ? "刷新中…" : "刷新"}
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      if (confirm(`删除订阅「${s.alias}」及其所有新闻?`)) {
                        del.mutate(s.id);
                      }
                    }}
                  >
                    删除
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
