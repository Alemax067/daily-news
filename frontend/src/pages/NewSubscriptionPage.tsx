import { useState } from "react";
import { api } from "../api/client";
import { Button } from "../components/Button";
import { ChatPanel } from "../components/ChatPanel";
import { NewSubscriptionForm } from "../components/NewSubscriptionForm";
import { useDraftSession } from "../hooks/useDraftSession";

export function NewSubscriptionPage() {
  const draft = useDraftSession();
  const [formOpen, setFormOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  // Set when we just created a session this turn — used to seed first message.
  const [autoFirst, setAutoFirst] = useState<string | null>(null);

  if (draft.loading) {
    return <div className="text-slate-500">检查草稿会话…</div>;
  }

  if (draft.session) {
    return (
      <ChatPanel
        sessionId={draft.session.id}
        autoFirstMessage={autoFirst ?? undefined}
        onClosed={() => {
          setAutoFirst(null);
          draft.clearDraft();
        }}
      />
    );
  }

  async function handleSubmit(alias: string, url: string, section: string) {
    setCreating(true);
    try {
      const { session_id } = await api.createSession(alias, url, section);
      const sess = await api.getSession(session_id);
      const seed = `列表页 URL: ${url}\n板块: ${section}\n请按工作流调试出 list 和 detail 选择器,搞定后告诉我点保存订阅。`;
      setAutoFirst(seed);
      setFormOpen(false);
      draft.setDraft(sess);
    } catch (e) {
      alert("创建会话失败:" + (e as Error).message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="text-center py-16">
      <p className="text-slate-600 mb-6">
        给一个新闻列表 URL + 板块名,智能体会试着抓样例,你确认后保存为订阅。
      </p>
      <Button onClick={() => setFormOpen(true)} className="text-base px-5 py-2.5">
        + 新建订阅
      </Button>
      <NewSubscriptionForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSubmit={handleSubmit}
        submitting={creating}
      />
    </div>
  );
}
