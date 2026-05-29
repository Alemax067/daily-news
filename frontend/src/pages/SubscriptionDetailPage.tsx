import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChatPanel } from "../components/ChatPanel";
import {
  useDeleteSubscription,
  useRefreshPreview,
  useSubscription,
  useSubscriptionPreview,
  useSubscriptionSessionLookup,
} from "../api/hooks";
import { Button } from "../components/Button";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

export function SubscriptionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const sub = useSubscription(id);
  const news = useSubscriptionPreview(id);
  const sessLookup = useSubscriptionSessionLookup(id);
  const refresh = useRefreshPreview();
  const del = useDeleteSubscription();
  const navigate = useNavigate();
  const [chatOpen, setChatOpen] = useState(false);

  if (sub.isLoading || news.isLoading) {
    return <div className="text-slate-500">加载中…</div>;
  }
  if (sub.error) {
    return <div className="text-red-600">加载失败:{(sub.error as Error).message}</div>;
  }
  if (!sub.data) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div className="min-w-0">
          <Link to="/subscriptions" className="text-sm text-slate-500 hover:underline">
            ← 返回订阅管理
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
            上次预览刷新:{fmtDate(sub.data.preview_refreshed_at)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            className="flex-1 sm:flex-none"
            disabled={refresh.isPending}
            onClick={() =>
              refresh.mutate(sub.data!.id, {
                onError: (e) => alert("刷新失败:" + (e as Error).message),
              })
            }
          >
            {refresh.isPending ? "刷新中…" : "刷新预览"}
          </Button>
          <Button
            variant="danger"
            className="flex-1 sm:flex-none"
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

      <p className="text-xs text-slate-500">
        这里看到的是预览(最近 5 条);自动化抓取的全量在
        <Link to={`/automation/subscriptions/${sub.data.id}`} className="text-blue-600 hover:underline mx-1">
          自动化页
        </Link>
      </p>

      {news.data && news.data.length > 0 ? (
        <div className="bg-white rounded-lg border border-slate-200 divide-y divide-slate-100">
          {news.data.map((n) => (
            <Link
              key={n.id}
              to={`/news/${n.id}?from=preview`}
              className="block px-4 py-3 hover:bg-slate-50"
            >
              <div className="font-medium text-slate-900">{n.title}</div>
              <div className="text-xs text-slate-500 mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                {n.pub_date && <span>{n.pub_date}</span>}
                {n.source && <span>· {n.source}</span>}
                <span className="sm:ml-auto">抓取于 {fmtDate(n.fetched_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 text-slate-500 bg-white rounded-lg border border-slate-200">
          暂无预览,点击「刷新预览」抓取最新 5 条
        </div>
      )}

      {/* 智能体对话:桌面 inline,移动 = 全屏弹层(始终渲染,切换容器类避免 SSE 中断) */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-700">智能体对话</h3>
          {sessLookup.data?.session_id && (
            <Button
              size="sm"
              variant="secondary"
              className="md:hidden"
              onClick={() => setChatOpen(true)}
            >
              打开对话
            </Button>
          )}
        </div>
        {sessLookup.isLoading ? (
          <div className="text-slate-500 text-sm">加载会话…</div>
        ) : sessLookup.data?.session_id ? (
          <>
            {/* 移动:全屏 modal 容器(默认隐藏);桌面:inline 占位容器 */}
            <div
              className={
                chatOpen
                  ? "fixed inset-0 z-50 bg-white flex flex-col"
                  : "hidden md:block"
              }
            >
              {/* 移动 modal header(只在 chatOpen 时可见) */}
              {chatOpen && (
                <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2 md:hidden">
                  <span className="text-base font-semibold">智能体对话</span>
                  <button
                    type="button"
                    aria-label="关闭对话"
                    onClick={() => setChatOpen(false)}
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
              )}
              <div className={chatOpen ? "flex-1 min-h-0" : "h-[480px]"}>
                <ChatPanel
                  sessionId={sessLookup.data.session_id}
                  mode="update"
                  heightClass="h-full"
                  onClosed={() => { /* update 模式 cancel 只是关闭,不做动作 */ }}
                  onConfirmed={() => {
                    alert("订阅规则已更新");
                    sub.refetch();
                    setChatOpen(false);
                  }}
                />
              </div>
            </div>
            {/* 移动端:未打开时显示一个占位提示 */}
            {!chatOpen && (
              <div className="md:hidden bg-white rounded-lg border border-slate-200 p-6 text-sm text-slate-600 text-center">
                点击右上「打开对话」继续修改选择器
              </div>
            )}
          </>
        ) : (
          <div className="bg-white rounded-lg border border-slate-200 p-6 text-sm text-slate-600">
            找不到该订阅对应的对话(老数据可能没有 session)。
          </div>
        )}
      </div>
    </div>
  );
}
