import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SessionView } from "../types";

const KEY = "daily-news.draftSessionId";

export interface DraftState {
  loading: boolean;
  session: SessionView | null;
}

/**
 * Manages the lifecycle of a "draft" subscription session.
 * - On mount: checks localStorage; if a draft id exists, validates it via GET.
 * - Provides explicit set/clear so callers can attach a freshly-created session.
 *
 * Treat the returned session as read-only metadata; the ChatPanel re-fetches
 * messages itself.
 */
export function useDraftSession() {
  const [state, setState] = useState<DraftState>({ loading: true, session: null });

  useEffect(() => {
    const id = localStorage.getItem(KEY);
    if (!id) {
      setState({ loading: false, session: null });
      return;
    }
    let cancelled = false;
    api
      .getSession(id)
      .then((s) => {
        if (cancelled) return;
        if (s.status === "draft") {
          setState({ loading: false, session: s });
        } else {
          localStorage.removeItem(KEY);
          setState({ loading: false, session: null });
        }
      })
      .catch(() => {
        if (cancelled) return;
        localStorage.removeItem(KEY);
        setState({ loading: false, session: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function setDraft(sess: SessionView) {
    localStorage.setItem(KEY, sess.id);
    setState({ loading: false, session: sess });
  }

  function clearDraft() {
    localStorage.removeItem(KEY);
    setState({ loading: false, session: null });
  }

  return { ...state, setDraft, clearDraft };
}
