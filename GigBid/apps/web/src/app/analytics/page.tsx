"use client";
import Shell, { State } from "@/components/Shell";
import { api } from "@/lib/api";
import { pct, useLoad } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="card"><div className="small muted">{label}</div><div style={{ fontSize: 26, fontWeight: 700 }}>{value}</div>{sub && <div className="small muted">{sub}</div>}</div>;
}

export default function Analytics() {
  const a = useLoad(() => api.GET("/api/analytics"), [], 10000);
  const d = a.data;
  const max = d ? Math.max(1, ...Object.values(d.funnel)) : 1;
  const b: any = d?.budgets || {};
  return (
    <Shell title="Analytics" sub="Funnel, reply rate, what your Connects bought, and what each run costs.">
      <State loading={a.loading} error={a.error}>
        {d && <>
          <div className="grid3">
            <Stat label="Reply rate" value={pct(d.reply_rate)} sub={`${d.funnel.replied} of ${d.funnel.submitted} proposals`} />
            <Stat label="Replies per 10 Connects" value={d.replies_per_10_connects.toFixed(2)} sub={`${d.connects_spent} Connects spent`} />
            <Stat label="Hire rate" value={pct(d.hire_rate)} sub={`${d.funnel.hired} hired`} />
          </div>
          <div className="card"><h2>Funnel</h2>
            <table><tbody>{Object.entries(d.funnel).map(([k, v]) => (
              <tr key={k}><td style={{ width: 120 }}>{k}</td><td><div className="bar" style={{ width: `${(100 * v) / max}%` }} role="img" aria-label={`${k}: ${v}`} /></td><td style={{ width: 60, textAlign: "right" }}>{v}</td></tr>))}</tbody></table>
          </div>
          <div className="grid2">
            <div className="card"><h2>Cost and latency per run</h2>
              <table><thead><tr><th>Measure</th><th>Measured</th><th>Declared budget</th></tr></thead><tbody>
                <tr><td>Cost per job analysed</td><td>${d.cost_per_job_usd.toFixed(5)}</td><td>${b.usd_per_job_analysed}</td></tr>
                <tr><td>Latency p50</td><td>{(d.latency_ms_p50 / 1000).toFixed(1)} s</td><td>-</td></tr>
                <tr><td>Latency p95</td><td>{(d.latency_ms_p95 / 1000).toFixed(1)} s</td><td>{b.p95_latency_s_per_proposal} s per proposal</td></tr>
                <tr><td>Total model spend</td><td>${d.cost_usd.toFixed(4)}</td><td>{d.tokens.toLocaleString()} tokens, {d.runs} runs</td></tr>
              </tbody></table></div>
            <div className="card"><h2>By category</h2>
              {d.by_category.length === 0 ? <div className="muted">No submitted proposals yet.</div> : <table><thead><tr><th>Category</th><th>Sent</th><th>Replied</th><th>Reply rate</th><th>Connects</th></tr></thead>
                <tbody>{d.by_category.map((c: any) => <tr key={c.name}><td>{c.name.replace(/_/g, " ")}</td><td>{c.sent}</td><td>{c.replied}</td><td>{pct(c.reply_rate)}</td><td>{c.connects}</td></tr>)}</tbody></table>}
              {d.by_strategy.length > 0 && <><h3 style={{ marginTop: 14 }}>By opening strategy</h3><table><tbody>{d.by_strategy.map((c: any) => <tr key={c.name}><td>{c.name.replace(/_/g, " ")}</td><td>{c.sent} sent</td><td>{pct(c.reply_rate)} replied</td></tr>)}</tbody></table>
                <div className="small muted">A controlled comparison with a significance test is in evals/results/experiment_ab.json.</div></>}
            </div>
          </div>
        </>}
      </State>
    </Shell>
  );
}
