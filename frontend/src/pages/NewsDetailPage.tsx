import { Link, useParams } from "react-router-dom";
import { useNewsDetail } from "../api/hooks";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

export function NewsDetailPage() {
  const { id } = useParams<{ id: string }>();
  const num = id ? parseInt(id, 10) : undefined;
  const { data, isLoading, error } = useNewsDetail(num);

  if (isLoading) return <div className="text-slate-500">加载中…</div>;
  if (error) return <div className="text-red-600">加载失败:{(error as Error).message}</div>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <Link
        to={`/subscriptions/${data.subscription_id}`}
        className="text-sm text-slate-500 hover:underline"
      >
        ← 返回新闻列表
      </Link>
      <article className="bg-white rounded-lg border border-slate-200 p-6">
        <h1 className="text-2xl font-semibold leading-tight">{data.title}</h1>
        <div className="text-xs text-slate-500 mt-2 flex gap-3 flex-wrap">
          {data.pub_date && <span>发布:{data.pub_date}</span>}
          {data.source && <span>来源:{data.source}</span>}
          <span>抓取:{fmtDate(data.fetched_at)}</span>
          <a
            href={data.url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline ml-auto"
          >
            原文 ↗
          </a>
        </div>
        <div className="mt-6 whitespace-pre-wrap leading-relaxed text-slate-800">
          {data.content || "(无正文)"}
        </div>
      </article>
    </div>
  );
}
