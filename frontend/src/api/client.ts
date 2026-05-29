import type {
  AppSettings,
  FetchTask,
  NewsItem,
  NewsItemDetail,
  QueueSnapshot,
  RefreshResult,
  SessionView,
  Subscription,
  SubscriptionDetail,
} from "../types";

const BASE = "/api";

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* ignore */ }
    throw Object.assign(new Error(detail), { status: r.status });
  }
  if (r.status === 204) return undefined as T;
  return (await r.json()) as T;
}

export const api = {
  // sessions
  createSession: (alias: string, url: string, section: string) =>
    request<{ session_id: string; status: string }>("POST", "/sessions", { alias, url, section }),
  getSession: (id: string) => request<SessionView>("GET", `/sessions/${id}`),
  deleteSession: (id: string) => request<{ ok: boolean }>("DELETE", `/sessions/${id}`),
  confirmSession: (id: string) =>
    request<{ subscription_id: string }>("POST", `/sessions/${id}/confirm`),

  // subscriptions
  listSubscriptions: () => request<Subscription[]>("GET", "/subscriptions"),
  getSubscription: (id: string) => request<SubscriptionDetail>("GET", `/subscriptions/${id}`),
  deleteSubscription: (id: string) =>
    request<{ ok: boolean }>("DELETE", `/subscriptions/${id}`),
  patchSubscription: (id: string, body: { auto_enabled: boolean }) =>
    request<Subscription>("PATCH", `/subscriptions/${id}`, body),
  listSubscriptionNews: (id: string, limit = 50, offset = 0) =>
    request<NewsItem[]>(
      "GET",
      `/subscriptions/${id}/news?limit=${limit}&offset=${offset}`,
    ),

  // 订阅管理 tab(预览)
  refreshPreview: (id: string) =>
    request<RefreshResult>("POST", `/subscriptions/${id}/refresh-preview`),
  listPreviewNews: (id: string) =>
    request<NewsItem[]>("GET", `/subscriptions/${id}/preview-news`),
  getSubscriptionSession: (id: string) =>
    request<{ session_id: string | null }>("GET", `/subscriptions/${id}/session`),
  updateFromSession: (subId: string, sessionId: string) =>
    request<{ ok: boolean }>(
      "POST",
      `/subscriptions/${subId}/update-from-session`,
      { session_id: sessionId },
    ),

  // 自动化
  listSubscriptionTasks: (id: string, limit = 20) =>
    request<FetchTask[]>("GET", `/subscriptions/${id}/tasks?limit=${limit}`),
  getAutomationSettings: () =>
    request<AppSettings>("GET", "/automation/settings"),
  setAutomationSettings: (body: AppSettings) =>
    request<AppSettings>("PUT", "/automation/settings", body),
  triggerAutomation: () =>
    request<{ enqueued: number }>("POST", "/automation/trigger"),
  getAutomationQueue: () =>
    request<QueueSnapshot>("GET", "/automation/queue"),

  // news
  getNews: (id: number) => request<NewsItemDetail>("GET", `/news/${id}`),
};
