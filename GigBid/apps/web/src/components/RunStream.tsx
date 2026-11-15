"use client";
import { useRunStream } from "@/lib/hooks";

/** Live node-by-node progress of an agent run (SSE). Used wherever work is in flight. */
export default function RunStream({ runId, onDone }: { runId?: string | null; onDone?: () => void }) {
  const { events, live } = useRunStream(runId, onDone);
  if (!runId) return null;
  const rows = events.filter((e) => ["node_end", "info", "interrupt", "error", "degraded", "node_error"].includes(e.type));
  const running = [...events].reverse().find((e) => e.type === "node_start" || e.type === "node_end");
  return (
    <div className="card" aria-live="polite">
      <h2><span className={`dot ${live ? "live" : ""}`} aria-hidden="true" />{live ? `Agents working${running?.type === "node_start" ? `: ${running.node}` : ""}...` : "Agent run"}</h2>
      {rows.length === 0 && <div className="muted small">Waiting for the first step...</div>}
      <ol className="timeline">
        {rows.map((e) => (
          <li key={e.id}>
            <span className="mono">{e.node || e.type}</span>
            <span className="small muted">{e.type === "node_end" ? `${e.payload.ms} ms - ${e.payload.tokens ?? 0} tok` : e.type}</span>
            <span className="small">{String(e.payload.summary ?? e.payload.message ?? (e.payload.errors as string[] | undefined)?.join("; ") ?? e.payload.error ?? "")}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
