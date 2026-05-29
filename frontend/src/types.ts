export type SubscriptionStatus = "draft" | "confirmed" | "abandoned";

export interface Subscription {
  id: string;
  alias: string;
  url: string;
  section: string;
  auto_enabled: boolean;
  last_refreshed_at: string | null;
  item_count: number;
  preview_refreshed_at: string | null;
  preview_item_count: number;
  created_at: string;
}

export interface ListSelectors {
  container: string;
  item: string;
  title: string;
  title_attr: "text" | "title";
  url: string;
  url_attr: string;
  url_regex: string | null;
  date: string | null;
  date_attr: "text";
  next_page_template: string | null;
}

export interface DetailSelectors {
  title: string | null;
  date: string | null;
  source: string | null;
  content: string;
}

export interface SubscriptionDetail extends Subscription {
  list_selectors: ListSelectors;
  detail_selectors: DetailSelectors | null;
}

export interface NewsItem {
  id: number;
  subscription_id: string;
  url: string;
  title: string;
  pub_date: string | null;
  source: string | null;
  fetched_at: string;
}

export interface NewsItemDetail extends NewsItem {
  content: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_calls?: { name: string; args: Record<string, unknown> }[] | null;
  tool_name?: string | null;
}

export interface SessionView {
  id: string;
  status: SubscriptionStatus;
  alias: string;
  url: string;
  section: string;
  subscription_id: string | null;
  is_streaming: boolean;
  messages: ChatMessage[];
}

export interface RefreshResult {
  added: number;
  fetched: number;
}

export type SSEEvent =
  | { event: "start"; data: { user_message?: string } }
  | { event: "token"; data: { text: string } }
  | { event: "tool_start"; data: { name: string; input: unknown } }
  | { event: "tool_end"; data: { name: string } }
  | { event: "done"; data: Record<string, never> }
  | { event: "error"; data: { error: string } }
  | { event: "snapshot"; data: QueueSnapshot };

// ===== automation =====

export type FetchTaskStatus = "pending" | "running" | "succeeded" | "failed";
export type FetchTaskSource = "manual" | "auto";

export interface FetchTask {
  id: number;
  subscription_id: string;
  subscription_alias: string | null;
  status: FetchTaskStatus;
  source: FetchTaskSource;
  enqueued_at: string;
  started_at: string | null;
  finished_at: string | null;
  items_added: number | null;
  items_fetched: number | null;
  pages_fetched: number | null;
  stop_reason: string | null;
  error: string | null;
}

export interface QueueSnapshot {
  running: FetchTask | null;
  pending: FetchTask[];
  recent_done: FetchTask[];
}

export type NewSubStrategy = "first_n" | "since_days";

export interface AppSettings {
  trigger_time: string;
  interval_hours: number;
  new_sub_strategy: NewSubStrategy;
  new_sub_n: number;
  last_auto_run_at?: string | null;
}
