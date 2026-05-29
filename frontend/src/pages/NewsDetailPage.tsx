import { Link, useParams, useSearchParams } from "react-router-dom";
import { useNewsDetail, usePreviewNewsDetail } from "../api/hooks";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

export function NewsDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const num = id ? parseInt(id, 10) : undefined;
  const from = params.get("from");
  const isPreview = from === "preview";
  const persistent = useNewsDetail(isPreview ? undefined : num);
  const preview = usePreviewNewsDetail(isPreview ? num : undefined);
  const { data, isLoading, error } = isPreview ? preview : persistent;

  if (isLoading) return <div className="text-slate-500">加载中…</div>;
  if (error) return <div className="text-red-600">加载失败:{(error as Error).message}</div>;
  if (!data) return null;

  const backTo =
    from === "automation"
      ? `/automation/subscriptions/${data.subscription_id}`
      : from === "timeline"
        ? `/timeline`
        : `/subscriptions/${data.subscription_id}`;
  const backLabel =
    from === "automation"
      ? "← 返回自动化新闻列表"
      : from === "timeline"
        ? "← 返回时间线"
        : "← 返回订阅预览";

  return (
    <div className="space-y-4">
      <Link to={backTo} className="text-sm text-slate-500 hover:underline">
        {backLabel}
      </Link>
      <article className="bg-white rounded-lg border border-slate-200 p-4 sm:p-6">
        <h1 className="text-xl sm:text-2xl font-semibold leading-tight">{data.title}</h1>
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
