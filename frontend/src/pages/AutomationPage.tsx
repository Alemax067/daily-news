import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  useAutomationQueue,
  useAutomationSettings,
  usePatchSubscription,
  useSubscriptions,
  useTriggerAutomation,
} from "../api/hooks";
import { streamAutomationQueue } from "../api/sse";
import type { FetchTask, QueueSnapshot, SSEEvent } from "../types";
import { AutomationSettingsModal } from "../components/AutomationSettingsModal";
import { Button } from "../components/Button";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("zh-CN", { hour12: false });
}

function statusBadge(status: FetchTask["status"]): { label: string; cls: string } {
  switch (status) {
    case "pending":
      return { label: "排队中", cls: "bg-slate-100 text-slate-600" };
    case "running":
      return { label: "运行中", cls: "bg-blue-100 text-blue-700" };
    case "succeeded":
      return { label: "✓", cls: "bg-emerald-100 text-emerald-700" };
    case "failed":
      return { label: "✗", cls: "bg-red-100 text-red-700" };
  }
}

function useLiveQueueSnapshot(initial: QueueSnapshot | undefined) {
  const [snap, setSnap] = useState<QueueSnapshot | undefined>(initial);
  useEffect(() => {
    if (initial) setSnap(initial);
  }, [initial]);

  useEffect(() => {
    const ac = new AbortController();
    let cancelled = false;
    (async () => {
      try {
        for await (const evt of streamAutomationQueue(ac.signal) as AsyncIterable<SSEEvent>) {
          if (cancelled) return;
          if (evt.event === "snapshot") {
            setSnap(evt.data as QueueSnapshot);
          }
        }
      } catch {
        // 断了就交给上层 5s polling 兜底
      }
    })();
    return () => {
      cancelled = true;
      ac.abort();
    };
  }, []);

  return snap;
}

export function AutomationPage() {
  const subs = useSubscriptions();
  const settings = useAutomationSettings();
  const queueQ = useAutomationQueue();
  const trigger = useTriggerAutomation();
  const patch = usePatchSubscription();
  const [openSettings, setOpenSettings] = useState(false);
  const navigate = useNavigate();

  const queue = useLiveQueueSnapshot(queueQ.data);

  return (
    <div className="flex flex-col h-[calc(100dvh-100px)] sm:h-[calc(100dvh-120px)]">
      {/* header */}
      <div className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-2 mb-3">
        <div>
          <h2 className="text-xl font-semibold">自动化</h2>
          {settings.data && (
            <div className="text-xs text-slate-500 mt-0.5">
              下次触发:{settings.data.trigger_time} · 每 {settings.data.interval_hours} 小时 ·
              新订阅 {settings.data.new_sub_strategy === "first_n" ? "首批 " : "近 "}
              {settings.data.new_sub_n}
              {settings.data.new_sub_strategy === "first_n" ? " 条" : " 天"}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            className="flex-1 sm:flex-none"
            onClick={() => setOpenSettings(true)}
          >
            设置
          </Button>
          <Button
            disabled={trigger.isPending}
            className="flex-1 sm:flex-none"
            onClick={() =>
              trigger.mutate(undefined, {
                onSuccess: (r) =>
                  alert(`已入队 ${r.enqueued} 个订阅(关闭自动开关的不入队)`),
                onError: (e) => alert("触发失败:" + (e as Error).message),
              })
            }
          >
            {trigger.isPending ? "触发中…" : "手动触发"}
          </Button>
        </div>
      </div>

      {/* subscriptions list (scrollable) */}
      <div className="flex-1 overflow-y-auto bg-white rounded-lg border border-slate-200">
        {subs.isLoading ? (
          <div className="p-6 text-slate-500 text-sm">加载中…</div>
        ) : !subs.data || subs.data.length === 0 ? (
          <div className="p-12 text-center text-slate-500 text-sm">
            暂无订阅,去
            <Link to="/new" className="text-blue-600 hover:underline mx-1">
              新建订阅
            </Link>
            创建第一个
          </div>
        ) : (
          <>
            {/* 桌面 table */}
            <table className="hidden md:table w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-600 sticky top-0">
                <tr>
                  <th className="px-4 py-2">别名</th>
                  <th className="px-4 py-2">URL</th>
                  <th className="px-4 py-2">条目</th>
                  <th className="px-4 py-2">上次抓取</th>
                  <th className="px-4 py-2 w-20 text-center">自动</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {subs.data.map((s) => (
                  <tr
                    key={s.id}
                    className="hover:bg-slate-50 cursor-pointer"
                    onClick={() => navigate(`/automation/subscriptions/${s.id}`)}
                  >
                    <td className="px-4 py-3 font-medium">{s.alias}</td>
                    <td className="px-4 py-3 text-slate-600 max-w-xs truncate">
                      {s.url}
                    </td>
                    <td className="px-4 py-3">{s.item_count}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {fmtDate(s.last_refreshed_at)}
                    </td>
                    <td className="px-4 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={s.auto_enabled}
                        onClick={() =>
                          patch.mutate({ id: s.id, auto_enabled: !s.auto_enabled })
                        }
                        className={
                          "relative inline-flex h-5 w-9 items-center rounded-full transition-colors " +
                          (s.auto_enabled ? "bg-blue-600" : "bg-slate-300")
                        }
                      >
                        <span
                          className={
                            "inline-block h-4 w-4 transform rounded-full bg-white transition-transform " +
                            (s.auto_enabled ? "translate-x-4" : "translate-x-0.5")
                          }
                        />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* 移动卡片 */}
            <div className="md:hidden divide-y divide-slate-100">
              {subs.data.map((s) => (
                <div
                  key={s.id}
                  className="px-4 py-3 active:bg-slate-50"
                  onClick={() => navigate(`/automation/subscriptions/${s.id}`)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="font-medium truncate">{s.alias}</div>
                      <div className="text-xs text-slate-500 truncate mt-0.5">
                        {s.url}
                      </div>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={s.auto_enabled}
                      onClick={(e) => {
                        e.stopPropagation();
                        patch.mutate({ id: s.id, auto_enabled: !s.auto_enabled });
                      }}
                      className={
                        "shrink-0 relative inline-flex h-6 w-11 items-center rounded-full transition-colors " +
                        (s.auto_enabled ? "bg-blue-600" : "bg-slate-300")
                      }
                    >
                      <span
                        className={
                          "inline-block h-5 w-5 transform rounded-full bg-white transition-transform " +
                          (s.auto_enabled ? "translate-x-5" : "translate-x-0.5")
                        }
                      />
                    </button>
                  </div>
                  <div className="text-xs text-slate-500 mt-2 flex flex-wrap gap-x-3 gap-y-0.5">
                    <span>条目 {s.item_count}</span>
                    <span>· 上次抓取 {fmtDate(s.last_refreshed_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* queue dock (sticky bottom) */}
      <QueueDock snap={queue} />

      <AutomationSettingsModal
        open={openSettings}
        initial={settings.data}
        onClose={() => setOpenSettings(false)}
      />
    </div>
  );
}

function QueueDock({ snap }: { snap: QueueSnapshot | undefined }) {
  const [expanded, setExpanded] = useState(false);

  if (!snap) {
    return (
      <div className="mt-3 bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-500">
        加载队列…
      </div>
    );
  }

  const summary = `${snap.running ? "1 个运行中" : "空闲"} · ${snap.pending.length} 排队 · ${snap.recent_done.length} 完成`;

  return (
    <div className="mt-3 bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-2 safe-bottom">
      {/* header:桌面/移动同样 */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-medium text-slate-700 shrink-0">队列</span>
          <span className="text-slate-500 truncate">{summary}</span>
        </div>
        {/* 移动端展开按钮 */}
        {(snap.pending.length > 0 || snap.recent_done.length > 0) && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="md:hidden text-slate-500 px-2 py-1 rounded hover:bg-slate-200 shrink-0"
          >
            {expanded ? "收起" : "展开"}
          </button>
        )}
      </div>

      {snap.running && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className={"px-1.5 rounded " + statusBadge(snap.running.status).cls}>
            {statusBadge(snap.running.status).label}
          </span>
          <span className="font-medium">{snap.running.subscription_alias ?? "—"}</span>
          <span className="text-slate-500">
            #{snap.running.id} · {snap.running.source} · 起 {fmtTime(snap.running.started_at)}
          </span>
        </div>
      )}

      {/* 桌面始终展示 pending/done;移动端按 expanded 展示 */}
      <div className={expanded ? "block" : "hidden md:block"}>
        {snap.pending.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-slate-500">排队中:</span>
            {snap.pending.slice(0, 8).map((t) => (
              <span
                key={t.id}
                className="px-1.5 rounded bg-slate-200 text-slate-700"
                title={`#${t.id} · ${t.source} · ${fmtTime(t.enqueued_at)}`}
              >
                {t.subscription_alias ?? `#${t.subscription_id.slice(0, 6)}`}
              </span>
            ))}
            {snap.pending.length > 8 && (
              <span className="text-slate-500">+{snap.pending.length - 8}</span>
            )}
          </div>
        )}

        {snap.recent_done.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <span className="text-slate-500">最近完成:</span>
            {snap.recent_done.slice(0, 6).map((t) => (
              <span
                key={t.id}
                className={"px-1.5 rounded " + statusBadge(t.status).cls}
                title={
                  t.error
                    ? t.error
                    : `添加 ${t.items_added ?? "?"} / 抓取 ${t.items_fetched ?? "?"} · ${t.stop_reason ?? ""}`
                }
              >
                {statusBadge(t.status).label} {t.subscription_alias ?? `#${t.subscription_id.slice(0, 6)}`}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
