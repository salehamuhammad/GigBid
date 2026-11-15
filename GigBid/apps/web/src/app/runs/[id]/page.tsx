"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import RunStream from "@/components/RunStream";
import Shell, { State, StatusBadge } from "@/components/Shell";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function RunDetail() {
  const { id } = useParams<{ id: string }>();
  const [share, setShare] = useState(false);
  const run = useLoad(() => api.GET("/api/runs/{run_id}", { params: { path: { run_id: id }, query: { share } } }), [id, share], 0);
  const r = run.data;
  const nodes: any[] = r?.nodes ?? []; const calls: any[] = r?.tool_calls ?? [];
  const total = nodes.reduce((a: number, n: any) => a + (n.ms || 0), 0) || 1;
  return (
    <Shell title="Agent run" sub={r ? `${r.kind} - ${r.ref}` : undefined} actions={r && <StatusBadge s={r.status} />}>
      <p><Link href="/runs">&larr; All runs</Link></p>
      <State loading={run.loading} error={run.error}>
        {r && <>
          <div className="card row spread">
            <div>Trace id <span className="mono">{r.trace_id}</span><div className="small muted">The same id is on the API request, every MCP tool call and the Marketplace audit log.</div></div>
            <div className="row"><span className="badge">{r.tokens.toLocaleString()} tokens</span><span className="badge">${r.cost_usd.toFixed(4)}</span><span className="badge">{(r.latency_ms / 1000).toFixed(1)} s</span>
              {r.langsmith_url ? <a href={r.langsmith_url} target="_blank" rel="noreferrer">Open in LangSmith</a> : <button className="link" onClick={() => setShare(true)}>Get LangSmith link</button>}</div>
          </div>
          {r.status === "running" && <RunStream runId={r.id} onDone={run.reload} />}
          <div className="card"><h2>Node by node</h2>
            <div className="tablewrap"><table>
              <thead><tr><th>Node</th><th>Latency</th><th style={{ width: "30%" }}>Share of time</th><th>Tokens</th><th>Cost</th><th>What it concluded</th></tr></thead>
              <tbody>{nodes.map((n: any, i: number) => (
                <tr key={i}><td className="mono">{n.node}</td><td>{n.ms} ms</td><td><div className="bar" style={{ width: `${Math.max(1, (100 * (n.ms || 0)) / total)}%` }} aria-hidden="true" /></td>
                  <td>{n.tokens ?? 0}</td><td>${Number(n.cost_usd ?? 0).toFixed(5)}</td><td className="small">{n.summary}</td></tr>))}</tbody>
            </table></div>
            {nodes.length === 0 && <div className="muted">No node finished in this run.</div>}
          </div>
          <div className="card"><h2>Tool calls (MCP)</h2>
            {calls.length === 0 ? <div className="muted">No tool calls recorded for this run.</div> : (
              <div className="tablewrap"><table>
                <thead><tr><th>Agent</th><th>Tool</th><th>Arguments</th><th>Result</th><th>ms</th></tr></thead>
                <tbody>{calls.map((c: any, i: number) => (
                  <tr key={i}><td>{c.agent}</td><td className="mono">{c.tool}</td><td className="mono small">{JSON.stringify(c.arguments).slice(0, 140)}</td>
                    <td className="mono small">{c.ok ? JSON.stringify(c.result).slice(0, 140) : <span className="badge bad">failed</span>}</td><td>{c.ms}</td></tr>))}</tbody>
              </table></div>)}
          </div>
          <div className="card"><h2>Event log</h2>
            <ol className="timeline">{r.events.map((e) => (
              <li key={e.id}><span className="small muted">{new Date(e.ts * 1000).toLocaleTimeString()}</span><span className="mono">{e.node || "-"}</span>
                <span className="small"><span className={`badge ${e.type.includes("error") ? "bad" : e.type === "interrupt" ? "warn" : ""}`}>{e.type}</span> {String((e.payload as any).summary ?? (e.payload as any).message ?? ((e.payload as any).errors || []).join("; ") ?? "")}</span></li>))}</ol>
          </div>
        </>}
      </State>
    </Shell>
  );
}
