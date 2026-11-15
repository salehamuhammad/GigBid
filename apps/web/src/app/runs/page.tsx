"use client";
import Link from "next/link";
import Shell, { State, StatusBadge } from "@/components/Shell";
import { api } from "@/lib/api";
import { ago, useLoad } from "@/lib/hooks";

export default function Runs() {
  const runs = useLoad(() => api.GET("/api/runs", { params: { query: { limit: 100 } } }), [], 5000);
  return (
    <Shell title="Agent runs" sub="Every run of the agent team, with its trace id, tokens, cost and latency.">
      <State loading={runs.loading} error={runs.error} empty={runs.data?.length === 0 && "No runs yet."}>
        <div className="card tablewrap" style={{ padding: 0 }}><table>
          <thead><tr><th>Run</th><th>Kind</th><th>Status</th><th>Tokens</th><th>Cost</th><th>Latency</th><th>Started</th><th>Trace id</th></tr></thead>
          <tbody>{runs.data?.map((r) => (
            <tr key={r.id}><td><Link href={`/runs/${r.id}`}>{r.ref}</Link></td><td>{r.kind}</td><td><StatusBadge s={r.status} /></td><td>{r.tokens.toLocaleString()}</td>
              <td>${r.cost_usd.toFixed(4)}</td><td>{(r.latency_ms / 1000).toFixed(1)} s</td><td className="small muted">{ago(r.started_at)}</td><td className="mono">{r.trace_id}</td></tr>))}</tbody>
        </table></div>
      </State>
    </Shell>
  );
}
