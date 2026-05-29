import { useState } from "react";
import { Link } from "react-router-dom";
import clsx from "clsx";
import { useTimeline, useTimelineTaskItems } from "../api/hooks";
import { api } from "../api/client";
import type { NewsItem, TimelineRun, TimelineSubscription } from "../types";
import { exportTimelineRun } from "../utils/exportTimeline";

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

function SourceBadge({ source }: { source: TimelineRun["source"] }) {
  const auto = source === "auto";
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
        auto
          ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
          : "bg-amber-50 text-amber-700 border border-amber-200",
      )}
    >
      {auto ? "⏰ 自动" : "👆 手动"}
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span
      className={clsx(
        "inline-block transition-transform text-slate-400",
        open && "rotate-90",
      )}
    >
      ▶
    </span>
  );
}

export function TimelinePage() {
  const { data, isLoading, error } = useTimeline(20);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-slate-900">时间线</h2>
        <p className="text-xs text-slate-500 mt-1">
          每条记录是一次自动化触发,展开看本次有更新的订阅。
        </p>
      </div>

      {isLoading && <div className="text-slate-500">加载中…</div>}
      {error && (
        <div className="text-red-600">加载失败:{(error as Error).message}</div>
      )}
      {data && data.length === 0 && (
        <div className="text-slate-500 bg-white rounded-lg border border-slate-200 p-6 text-center">
          还没有触发记录。到自动化页点「手动触发」或等下次定时。
        </div>
      )}
      {data && data.map((run) => <RunCard key={run.run_id} run={run} />)}
    </div>
  );
}

function RunCard({ run }: { run: TimelineRun }) {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const subsWithUpdates = run.subscriptions.length;

  async function handleExport(e: React.MouseEvent) {
    e.stopPropagation();
    if (exporting || run.total_items_added === 0) return;
    setExportError(null);
    setExporting(true);
    try {
      const data = await api.exportTimelineRun(run.run_id);
      await exportTimelineRun(data);
    } catch (err) {
      setExportError((err as Error).message);
    } finally {
      setExporting(false);
    }
  }

  const canExport = run.total_items_added > 0;

  return (
    <div className="bg-white rounded-lg border border-slate-200">
      <div className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-3 flex-1 min-w-0 text-left"
        >
          <Chevron open={open} />
          <SourceBadge source={run.source} />
          <span className="text-sm text-slate-700">{fmtDateTime(run.triggered_at)}</span>
          <span className="ml-auto flex items-center gap-3 text-xs text-slate-500">
            <span>
              {run.task_count} 个订阅
              {run.failed_count > 0 && (
                <span className="text-red-600 ml-1">({run.failed_count} 失败)</span>
              )}
            </span>
            <span>·</span>
            <span>
              {subsWithUpdates > 0 ? (
                <>
                  <span className="text-emerald-700 font-medium">
                    {subsWithUpdates}
                  </span>{" "}
                  个订阅有更新,共
                  <span className="text-emerald-700 font-medium ml-1">
                    +{run.total_items_added}
                  </span>{" "}
                  条
                </>
              ) : (
                <span>无更新</span>
              )}
            </span>
          </span>
        </button>
        <button
          type="button"
          onClick={handleExport}
          disabled={!canExport || exporting}
          title={
            canExport
              ? "导出为 xlsx"
              : "本次触发没有新增条目"
          }
          className={clsx(
            "ml-2 px-2.5 py-1 rounded text-xs font-medium border whitespace-nowrap",
            canExport && !exporting
              ? "bg-white text-slate-700 border-slate-300 hover:bg-slate-100"
              : "bg-slate-50 text-slate-400 border-slate-200 cursor-not-allowed",
          )}
        >
          {exporting ? "导出中…" : "↓ 导出"}
        </button>
      </div>
      {exportError && (
        <div className="px-4 pb-2 text-xs text-red-600">
          导出失败:{exportError}
        </div>
      )}

      {open && (
        <div className="border-t border-slate-100">
          {run.subscriptions.length === 0 ? (
            <div className="px-12 py-3 text-sm text-slate-500">
              本次触发没有任何订阅产生新条目。
            </div>
          ) : (
            run.subscriptions.map((s) => <SubRow key={s.task_id} sub={s} />)
          )}
        </div>
      )}
    </div>
  );
}

function SubRow({ sub }: { sub: TimelineSubscription }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 pl-10 pr-4 py-2.5 text-left hover:bg-slate-50"
      >
        <Chevron open={open} />
        <span className="text-sm font-medium text-slate-800">
          {sub.subscription_alias ?? sub.subscription_id.slice(0, 8)}
        </span>
        <span className="ml-auto text-xs text-emerald-700 font-medium">
          +{sub.items_added}
        </span>
      </button>
      {open && <ItemList taskId={sub.task_id} subscriptionId={sub.subscription_id} />}
    </div>
  );
}

function ItemList({
  taskId,
  subscriptionId,
}: {
  taskId: number;
  subscriptionId: string;
}) {
  const { data, isLoading, error } = useTimelineTaskItems(taskId);

  if (isLoading) {
    return <div className="pl-16 pr-4 py-2 text-xs text-slate-500">加载中…</div>;
  }
  if (error) {
    return (
      <div className="pl-16 pr-4 py-2 text-xs text-red-600">
        加载失败:{(error as Error).message}
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <div className="pl-16 pr-4 py-2 text-xs text-slate-500">(无新增)</div>
    );
  }
  return (
    <div className="bg-slate-50/60">
      {data.map((n) => (
        <NewsRow key={n.id} item={n} subscriptionId={subscriptionId} />
      ))}
    </div>
  );
}

function NewsRow({
  item,
  subscriptionId: _sub,
}: {
  item: NewsItem;
  subscriptionId: string;
}) {
  return (
    <Link
      to={`/news/${item.id}?from=timeline`}
      className="block pl-16 pr-4 py-2 hover:bg-slate-100"
    >
      <div className="text-sm text-slate-800">{item.title}</div>
      <div className="text-xs text-slate-500 mt-0.5 flex gap-3">
        {item.pub_date && <span>{item.pub_date}</span>}
        {item.source && <span>{item.source}</span>}
      </div>
    </Link>
  );
}
