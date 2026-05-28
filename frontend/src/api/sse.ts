import type { SSEEvent } from "../types";

/**
 * POST /sessions/{id}/messages and yield parsed SSE events as an async generator.
 * Caller can `for await (const e of streamMessage(...))` and update UI.
 * Pass an AbortSignal to cancel the in-flight request from outside.
 */
export async function* streamMessage(
  sessionId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent, void, void> {
  const r = await fetch(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "text/event-stream",
    },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j.detail) detail = String(j.detail);
    } catch { /* ignore */ }
    throw Object.assign(new Error(detail), { status: r.status });
  }
  if (!r.body) throw new Error("no body");

  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const evt = parseBlock(block);
      if (evt) yield evt;
    }
  }
}

function parseBlock(block: string): SSEEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  let data: unknown = dataLines.join("\n");
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch { /* ignore non-JSON */ }
  return { event, data } as SSEEvent;
}
