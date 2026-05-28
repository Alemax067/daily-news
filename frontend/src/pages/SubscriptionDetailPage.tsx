import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useDeleteSubscription,
  useRefreshSubscription,
  useSubscription,
  useSubscriptionNews,
} from "../api/hooks";
import { Button } from "../components/Button";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

export function SubscriptionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const sub = useSubscription(id);
  const news = useSubscriptionNews(id);
  const refresh = useRefreshSubscription();
  const del = useDeleteSubscription();
  const navigate = useNavigate();

  if (sub.isLoading || news.isLoading) {
    return <div className="text-slate-500">加载中…</div>;
  }
  if (sub.error) {
    return <div className="text-red-600">加载失败:{(sub.error as Error).message}</div>;
  }
  if (!sub.data) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <Link to="/subscriptions" className="text-sm text-slate-500 hover:underline">
            ← 返回订阅列表
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
          <div className="text-xs text-slate-500 mt-1">
            上次刷新:{fmtDate(sub.data.last_refreshed_at)} · 共 {sub.data.item_count} 条
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={refresh.isPending}
            onClick={() =>
              refresh.mutate(sub.data!.id, {
                onError: (e) => alert("刷新失败:" + (e as Error).message),
              })
            }
          >
            {refresh.isPending ? "刷新中…" : "刷新订阅"}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (confirm("删除该订阅及全部新闻?")) {
                del.mutate(sub.data!.id, {
                  onSuccess: () => navigate("/subscriptions"),
                });
              }
            }}
          >
            删除
          </Button>
        </div>
      </div>

      {news.data && news.data.length > 0 ? (
        <div className="bg-white rounded-lg border border-slate-200 divide-y divide-slate-100">
          {news.data.map((n) => (
            <Link
              key={n.id}
              to={`/news/${n.id}`}
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
        <div className="text-center py-12 text-slate-500 bg-white rounded-lg border border-slate-200">
          暂无新闻,点击「刷新订阅」抓取最新 5 条
        </div>
      )}
    </div>
  );
}
