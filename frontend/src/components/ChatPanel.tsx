import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { resumeStream, streamMessage } from "../api/sse";
import type { ChatMessage, SSEEvent, SessionView } from "../types";
import { Button } from "./Button";

interface Props {
  sessionId: string;
  /** if given, automatically sent on first mount when no messages exist yet */
  autoFirstMessage?: string;
  onClosed: () => void;
  /** "create" → POST /confirm. "update" → POST /update-from-session.
   *  Default 'create' preserves the new-subscription flow.
   */
  mode?: "create" | "update";
  /** Outer height class. Default fills page; embedded views pass `h-full`. */
  heightClass?: string;
  /** Called after a successful confirm/update. Defaults to navigate to /subscriptions in create mode. */
  onConfirmed?: (subscriptionId: string) => void;
}

interface LiveTool {
  name: string;
  ended: boolean;
}

export function ChatPanel({
  sessionId,
  autoFirstMessage,
  onClosed,
  mode = "create",
  heightClass = "h-[calc(100dvh-200px)] min-h-[500px]",
  onConfirmed,
}: Props) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [session, setSession] = useState<SessionView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [liveText, setLiveText] = useState("");
  const [liveTools, setLiveTools] = useState<LiveTool[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const autoSentRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Load (or reload) session messages from backend
  async function reload(): Promise<SessionView | null> {
    try {
      const s = await api.getSession(sessionId);
      setSession(s);
      setLoadError(null);
      return s;
    } catch (e) {
      setLoadError((e as Error).message);
      return null;
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const s = await reload();
      if (cancelled || !s) return;
      // If the agent is still running on the server (e.g., we just refreshed
      // mid-reply), re-attach to its event stream so the in-flight reply
      // resumes seamlessly. Buffer is replayed from index 0, then live tail.
      if (s.is_streaming) {
        void consume(() => resumeStream(sessionId, makeAbort().signal));
        return;
      }
      // Auto-send the first templated message only if conversation is empty.
      if (
        autoFirstMessage &&
        s.messages.length === 0 &&
        !autoSentRef.current
      ) {
        autoSentRef.current = true;
        void send(autoFirstMessage);
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Auto-scroll to bottom on message updates
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [session?.messages.length, liveText, pendingUser, liveTools.length]);

  function makeAbort(): AbortController {
    const ac = new AbortController();
    abortRef.current = ac;
    return ac;
  }

  function applyEvent(evt: SSEEvent) {
    if (evt.event === "start") {
      if (evt.data.user_message) setPendingUser(evt.data.user_message);
    } else if (evt.event === "token") {
      setLiveText((t) => t + evt.data.text);
    } else if (evt.event === "tool_start") {
      setLiveTools((ts) => [...ts, { name: evt.data.name, ended: false }]);
    } else if (evt.event === "tool_end") {
      setLiveTools((ts) => {
        const idx = ts.findIndex((t) => t.name === evt.data.name && !t.ended);
        if (idx < 0) return ts;
        const next = ts.slice();
        next[idx] = { ...next[idx], ended: true };
        return next;
      });
    } else if (evt.event === "error") {
      setStreamError(evt.data.error);
    }
  }

  async function consume(open: () => AsyncIterable<SSEEvent>) {
    if (streaming) return;
    setStreaming(true);
    setLiveText("");
    setLiveTools([]);
    setStreamError(null);
    try {
      for await (const evt of open()) {
        applyEvent(evt);
        if (evt.event === "done") break;
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setStreamError((e as Error).message);
      }
    } finally {
      setStreaming(false);
      setPendingUser(null);
      setLiveText("");
      setLiveTools([]);
      abortRef.current = null;
      await reload();
    }
  }

  async function send(content: string) {
    if (streaming) return;
    setPendingUser(content);
    const ac = makeAbort();
    await consume(() => streamMessage(sessionId, content, ac.signal));
  }

  async function handleSend() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    await send(text);
  }

  async function handleConfirm() {
    setConfirming(true);
    try {
      let subId: string;
      if (mode === "update") {
        if (!session?.subscription_id) {
          throw new Error("session 没有关联订阅,无法更新");
        }
        subId = session.subscription_id;
        await api.updateFromSession(subId, sessionId);
        qc.invalidateQueries({ queryKey: ["subscription", subId] });
      } else {
        const r = await api.confirmSession(sessionId);
        subId = r.subscription_id;
      }
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      if (onConfirmed) {
        onConfirmed(subId);
      } else {
        onClosed();
        if (mode === "create") navigate("/subscriptions");
      }
    } catch (e) {
      alert(
        (mode === "update" ? "更新失败:" : "保存失败:") + (e as Error).message,
      );
    } finally {
      setConfirming(false);
    }
  }

  async function handleCancel() {
    if (mode === "update") {
      // update 模式不删 session,只关闭面板
      onClosed();
      return;
    }
    if (!confirm("放弃本次对话?草稿会被清除。")) return;
    abortRef.current?.abort();
    try {
      await api.deleteSession(sessionId);
    } catch { /* ignore */ }
    onClosed();
  }

  if (loadError) {
    return (
      <div className="bg-white rounded-lg border border-red-200 p-6 text-red-700">
        <div className="font-medium">无法加载会话:{loadError}</div>
        <Button className="mt-3" variant="secondary" onClick={onClosed}>
          关闭
        </Button>
      </div>
    );
  }
  if (!session) {
    return <div className="text-slate-500">加载会话…</div>;
  }

  return (
    <div className={`bg-white rounded-lg border border-slate-200 flex flex-col ${heightClass}`}>
      {/* header */}
      <div className="border-b border-slate-200 px-4 py-3 flex items-start justify-between">
        <div className="text-sm">
          <div className="font-medium">{session.alias}</div>
          <div className="text-slate-500 text-xs">{session.section}</div>
          <div className="text-slate-500 text-xs break-all">{session.url}</div>
        </div>
        <div className="flex gap-2">
          {mode === "create" && (
            <Button variant="ghost" onClick={handleCancel}>
              取消
            </Button>
          )}
          <Button
            disabled={confirming || streaming}
            onClick={handleConfirm}
            title={
              mode === "update"
                ? "用当前对话学到的选择器覆盖订阅规则"
                : "把当前规则入库,生成正式订阅"
            }
          >
            {confirming
              ? mode === "update"
                ? "更新中…"
                : "保存中…"
              : mode === "update"
                ? "更新订阅"
                : "保存订阅"}
          </Button>
        </div>
      </div>

      {/* messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden p-4 space-y-4">
        {session.messages.map((m, i) => (
          <MessageBubble key={i} m={m} />
        ))}
        {pendingUser && <MessageBubble m={{ role: "user", content: pendingUser }} />}
        {liveTools.length > 0 && (
          <div className="space-y-1">
            {liveTools.map((t, i) => (
              <div key={i} className="text-xs text-slate-500">
                🔧 {t.ended ? `已调用 ${t.name}` : `调用 ${t.name}…`}
              </div>
            ))}
          </div>
        )}
        {streaming && (
          <MessageBubble
            m={{ role: "assistant", content: liveText }}
            streaming
          />
        )}
        {streamError && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-2">
            {streamError}
          </div>
        )}
      </div>

      {/* input */}
      <div className="border-t border-slate-200 p-3 safe-bottom">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={streaming}
            rows={2}
            placeholder={
              streaming
                ? "智能体正在回复…"
                : "输入反馈,例如「标题对应不上,清缓存重试」或「可以了,保存订阅」"
            }
            className="flex-1 px-3 py-2 border border-slate-300 rounded-md text-base resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                void handleSend();
              }
            }}
          />
          <Button onClick={handleSend} disabled={streaming || !input.trim()}>
            发送
          </Button>
        </div>
        <div className="text-xs text-slate-400 mt-1">Ctrl/⌘ + Enter 发送</div>
      </div>
    </div>
  );
}

function MessageBubble({
  m,
  streaming,
}: {
  m: ChatMessage;
  streaming?: boolean;
}) {
  if (m.role === "tool") {
    return (
      <div className="text-xs text-slate-500 bg-slate-50 rounded p-2 border border-slate-200">
        <div className="font-medium">🔧 工具结果 · {m.tool_name}</div>
        <div className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-all font-mono">
          {m.content.length > 600 ? m.content.slice(0, 600) + "…" : m.content}
        </div>
      </div>
    );
  }
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-blue-600 text-white rounded-lg px-4 py-2 max-w-[80%] whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          {m.content}
        </div>
      </div>
    );
  }
  // assistant
  const showToolCalls = m.tool_calls && m.tool_calls.length > 0;
  const hasText = m.content.trim().length > 0;
  if (!hasText && !showToolCalls && !streaming) return null;
  return (
    <div className="flex justify-start">
      <div className="bg-slate-100 text-slate-900 rounded-lg px-4 py-2 max-w-[85%] whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {showToolCalls && (
          <div className="text-xs text-slate-500 mb-1">
            {m.tool_calls!.map((t, i) => (
              <div key={i}>🔧 调用 {t.name}</div>
            ))}
          </div>
        )}
        {m.content}
        {streaming && <span className="inline-block w-1 h-4 bg-slate-400 align-text-bottom animate-pulse ml-0.5" />}
      </div>
    </div>
  );
}
