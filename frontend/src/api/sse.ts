import type { SSEEvent } from "../types";

/**
 * POST /sessions/{id}/messages — start a new agent turn and stream events.
 * The server runs the agent in a detached background task, so a client
 * disconnect (refresh) does NOT abort the agent. Use `resumeStream` to
 * re-attach to an in-flight run after a refresh.
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
  yield* fromResponse(r, signal);
}

/**
 * GET /sessions/{id}/stream — re-attach to an active or just-completed run.
 * Server replays its event buffer from index 0, then streams the live tail.
 * 404 if no run is registered for the session.
 */
export async function* resumeStream(
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent, void, void> {
  const r = await fetch(`/api/sessions/${sessionId}/stream`, {
    method: "GET",
    headers: { accept: "text/event-stream" },
    signal,
  });
  yield* fromResponse(r, signal);
}

/**
 * GET /automation/queue/stream — long-lived SSE pushing queue snapshots
 * each time the worker flips a task status. 5s heartbeat tick from server.
 */
export async function* streamAutomationQueue(
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent, void, void> {
  const r = await fetch(`/api/automation/queue/stream`, {
    method: "GET",
    headers: { accept: "text/event-stream" },
    signal,
  });
  yield* fromResponse(r, signal);
}

async function* fromResponse(
  r: Response,
  _signal?: AbortSignal,
): AsyncGenerator<SSEEvent, void, void> {
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
