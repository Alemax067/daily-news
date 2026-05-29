import { useEffect, useState } from "react";
import { useSetAutomationSettings } from "../api/hooks";
import type { AppSettings, NewSubStrategy } from "../types";
import { Button } from "./Button";
import { Modal } from "./Modal";
import { NumberInput } from "./NumberInput";

interface Props {
  open: boolean;
  initial: AppSettings | undefined;
  onClose: () => void;
}

const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = [0, 30] as const;

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

export function AutomationSettingsModal({ open, initial, onClose }: Props) {
  const set = useSetAutomationSettings();
  const [hour, setHour] = useState(9);
  const [minute, setMinute] = useState<0 | 30>(0);
  const [interval, setInterval] = useState<12 | 24>(24);
  const [strategy, setStrategy] = useState<NewSubStrategy>("first_n");
  const [n, setN] = useState(20);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !initial) return;
    const [h, m] = initial.trigger_time.split(":").map((s) => parseInt(s, 10));
    setHour(Number.isFinite(h) ? h : 9);
    setMinute(m === 30 ? 30 : 0);
    setInterval(initial.interval_hours === 12 ? 12 : 24);
    setStrategy(initial.new_sub_strategy);
    setN(initial.new_sub_n);
    setErr(null);
  }, [open, initial]);

  const nMax = strategy === "first_n" ? 100 : 90;
  // strategy 切换时如果 n 超过新的 max,clamp 到 max
  useEffect(() => {
    if (n > nMax) setN(nMax);
  }, [strategy, n, nMax]);

  async function handleSave() {
    setErr(null);
    const body: AppSettings = {
      trigger_time: `${pad2(hour)}:${pad2(minute)}`,
      interval_hours: interval,
      new_sub_strategy: strategy,
      new_sub_n: n,
    };
    try {
      await set.mutateAsync(body);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="自动化抓取设置">
      <div className="space-y-4 text-sm">
        <div>
          <label className="block text-slate-700 font-medium mb-1.5">
            触发时间(本地时区,仅整点/半点)
          </label>
          <div className="flex items-center gap-2">
            <select
              value={hour}
              onChange={(e) => setHour(parseInt(e.target.value, 10))}
              className="border border-slate-300 rounded px-2 py-1"
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {pad2(h)}
                </option>
              ))}
            </select>
            <span>:</span>
            <select
              value={minute}
              onChange={(e) => setMinute(parseInt(e.target.value, 10) as 0 | 30)}
              className="border border-slate-300 rounded px-2 py-1"
            >
              {MINUTES.map((m) => (
                <option key={m} value={m}>
                  {pad2(m)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-slate-700 font-medium mb-1.5">
            抓取间隔
          </label>
          <div className="flex gap-4">
            {[24, 12].map((h) => (
              <label key={h} className="inline-flex items-center gap-1.5">
                <input
                  type="radio"
                  name="interval"
                  value={h}
                  checked={interval === h}
                  onChange={() => setInterval(h as 12 | 24)}
                />
                每 {h} 小时
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-slate-700 font-medium mb-1.5">
            新订阅首次抓取策略
          </label>
          <div className="flex flex-col gap-2">
            <label className="inline-flex items-center gap-1.5">
              <input
                type="radio"
                name="strategy"
                checked={strategy === "first_n"}
                onChange={() => setStrategy("first_n")}
              />
              抓取最新
              <NumberInput
                value={n}
                min={1}
                max={strategy === "first_n" ? 100 : 100}
                onChange={setN}
                disabled={strategy !== "first_n"}
              />
              条 (1..100)
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input
                type="radio"
                name="strategy"
                checked={strategy === "since_days"}
                onChange={() => setStrategy("since_days")}
              />
              抓取最近
              <NumberInput
                value={n}
                min={1}
                max={strategy === "since_days" ? 90 : 90}
                onChange={setN}
                disabled={strategy !== "since_days"}
              />
              天 (1..90)
            </label>
          </div>
        </div>

        {err && (
          <div className="text-red-600 bg-red-50 border border-red-200 rounded p-2 text-xs">
            {err}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button disabled={set.isPending} onClick={handleSave}>
            {set.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
