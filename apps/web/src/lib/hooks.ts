"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { auth, errorText } from "./api";

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Load data, optionally re-polling. Gives every screen the same loading / error / empty handling. */
export function useLoad<T>(fn: () => Promise<Result<T>>, deps: unknown[] = [], pollMs = 0) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const f = useRef(fn);
  f.current = fn;
  const reload = useCallback(async () => {
    try {
      const r = await f.current();
      if (r.error !== undefined) setError(errorText(r.error));
      else { setData(r.data); setError(null); }
    } catch {
      setError("Cannot reach the GigBid API. Check that it is running.");
    } finally { setLoading(false); }
  }, []);
  useEffect(() => {
    reload();
    if (!pollMs) return;
    const t = setInterval(() => { if (!document.hidden) reload(); }, pollMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload };
}

export type RunEvent = { id: number; ts: number; node: string; type: string; payload: Record<string, unknown> };

/** Follow an agent run over Server-Sent Events. Events are persisted, so a refresh replays them. */
export function useRunStream(runId: string | null | undefined, onDone?: () => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [live, setLive] = useState(false);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!runId) return;
    setEvents([]);
    const es = new EventSource(`/api/runs/${runId}/stream?token=${encodeURIComponent(auth.get() || "")}`);
    setLive(true);
    const push = (e: MessageEvent) => setEvents((xs) => [...xs, JSON.parse(e.data)]);
    for (const t of ["node_start", "node_end", "node_error", "info", "interrupt", "error", "degraded", "end"]) es.addEventListener(t, push as EventListener);
    es.addEventListener("done", () => { setLive(false); es.close(); done.current?.(); });
    es.onerror = () => { setLive(false); };
    return () => es.close();
  }, [runId]);
  return { events, live };
}

export const money = (n?: number | null) => (n == null ? "-" : "$" + Math.round(n).toLocaleString("en-US"));
export const pct = (n?: number | null) => (n == null ? "-" : Math.round(n * 100) + "%");
export const ago = (ts?: number | null) => {
  if (!ts) return "-";
  const s = Date.now() / 1000 - ts;
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : `${Math.floor(s / 86400)} d ago`;
};
export const budgetText = (b?: Record<string, unknown>) =>
  !b || !b.type ? "-" : b.type === "hourly" ? `$${b.min}-$${b.max}/h` : `${money(b.max as number)} fixed`;
