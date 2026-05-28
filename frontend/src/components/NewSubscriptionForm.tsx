import { useState } from "react";
import { Button } from "./Button";
import { Modal } from "./Modal";

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (alias: string, url: string, section: string) => void | Promise<void>;
  submitting?: boolean;
}

export function NewSubscriptionForm({ open, onClose, onSubmit, submitting }: Props) {
  const [alias, setAlias] = useState("");
  const [url, setUrl] = useState("");
  const [section, setSection] = useState("");

  return (
    <Modal open={open} onClose={onClose} title="新建订阅">
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const a = alias.trim();
          const u = url.trim();
          const s = section.trim();
          if (!a || !u || !s) return;
          await onSubmit(a, u, s);
        }}
        className="space-y-4"
      >
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            订阅别名
          </label>
          <input
            type="text"
            required
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="上海政府要闻"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-slate-500 mt-1">
            用于在订阅列表里识别这条订阅,需唯一。
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            列表页 URL
          </label>
          <input
            type="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.shanghai.gov.cn/nw4411/index.html"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            板块名
          </label>
          <input
            type="text"
            required
            value={section}
            onChange={(e) => setSection(e.target.value)}
            placeholder="上海要闻"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-slate-500 mt-1">
            智能体会根据板块名在页面上定位对应的新闻列表。
          </p>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? "创建中…" : "下一步:开始对话"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
