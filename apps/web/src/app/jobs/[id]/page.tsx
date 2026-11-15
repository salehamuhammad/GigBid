"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import RunStream from "@/components/RunStream";
import Shell, { State, StatusBadge } from "@/components/Shell";
import { api, errorText } from "@/lib/api";
import { budgetText, money, pct, useLoad } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const job = useLoad(() => api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }), [id], 4000);
  const [msg, setMsg] = useState<string | null>(null);
  const j = job.data; const a: any = j?.analysis || {};
  const working = j && ["new", "analysing", "queued"].includes(j.status);
  async function act(kind: "analyze" | "skip") {
    const r = kind === "analyze" ? await api.POST("/api/jobs/{job_id}/analyze", { params: { path: { job_id: id } } }) : await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: id } } });
    setMsg(r.error ? errorText(r.error) : r.data?.detail || "Done"); job.reload();
  }
  return (
    <Shell title={j?.title || "Job"} sub={j ? `${j.category.replace(/_/g, " ")} - ${budgetText(j.budget)} - ${j.connects_cost ?? "-"} Connects` : undefined}
      actions={j && <>
        <StatusBadge s={j.status} />
        {(j.proposal || j.approval_id) && <Link className="btn" href={`/studio/${j.job_id}`}><strong>{j.approval_id ? "Review and approve" : "Open proposal"}</strong></Link>}
        {!["submitted", "awaiting_approval", "analysing"].includes(j.status) && <button onClick={() => act("analyze")}>Analyse again</button>}
        {!["submitted", "skipped"].includes(j.status) && <button onClick={() => act("skip")}>Skip</button>}
      </>}>
      <p><Link href="/inbox">&larr; Inbox</Link></p>
      {msg && <div className="banner info" role="status">{msg}</div>}
      <State loading={job.loading} error={job.error}>
        {j && <>
          {j.note && <div className={`banner ${["blocked", "needs_attention", "dead_letter"].includes(j.status) ? "bad" : "warn"}`}>{j.note}</div>}
          {working && <RunStream runId={j.run_id} onDone={job.reload} />}
          {a.decision?.action && (
            <div className="card">
              <h2>Recommendation: <span className={`badge ${a.decision.action === "bid" ? "ok" : a.decision.action === "watch" ? "warn" : ""}`}>{a.decision.action}</span></h2>
              <ul>{a.decision.reasons?.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
            </div>
          )}
          <div className="grid2">
            <div className="card">
              <h2>Job post</h2>
              {a.injection?.flagged && <div className="note">This post contained text aimed at AI tools. It was removed before any agent read it and has been ignored.</div>}
              <div style={{ whiteSpace: "pre-wrap" }}>{j.description}</div>
              {(j.screening_questions ?? []).length > 0 && <><h3 style={{ marginTop: 12 }}>Screening questions</h3><ol>{(j.screening_questions ?? []).map((q) => <li key={q}>{q}</li>)}</ol></>}
            </div>
            <div>
              <div className="card">
                <h2>Risk {a.risk && <span className={`badge ${a.risk.level === "high" ? "bad" : a.risk.level === "medium" ? "warn" : "ok"}`}>{a.risk.level} - {pct(a.risk.score)}</span>}</h2>
                {!a.risk ? <div className="muted">Not analysed yet.</div> : a.risk.flags.length === 0 ? <p>No risk signals. {a.risk.explanation}</p> : (
                  <ul>{a.risk.flags.map((f: any, i: number) => <li key={i}><strong>{f.code.replace(/_/g, " ")}</strong> <span className="badge">{f.severity}</span><div className="small muted">&ldquo;{f.evidence}&rdquo;</div></li>)}</ul>
                )}
                {a.client && <div className="small muted">Client: {a.client.payment_verified ? "payment verified" : "payment NOT verified"} - {money(a.client.total_spent_usd)} spent - {a.client.hires} hires - rating {a.client.rating || "n/a"} - since {a.client.member_since}</div>}
              </div>
              <div className="card">
                <h2>Price {a.price?.bid_amount && <span className="badge info">{money(a.price.bid_amount)}{a.price.bid_type === "hourly" ? "/h" : ""}</span>}</h2>
                {!a.price?.rationale ? <div className="muted">Priced only for jobs worth bidding on.</div> : <ul>{a.price.rationale.map((r: string, i: number) => <li key={i} className="small">{r}</li>)}</ul>}
              </div>
            </div>
          </div>
          <div className="card">
            <h2>Requirement &rarr; evidence {a.fit && <span className="badge info">fit {pct(a.fit.score)}</span>}</h2>
            {!a.fit ? <div className="muted">Not analysed yet.</div> : (
              <div className="tablewrap"><table>
                <thead><tr><th>What the client needs</th><th>Proven?</th><th>Evidence from your portfolio</th></tr></thead>
                <tbody>{a.fit.matrix.map((m: any, i: number) => (
                  <tr key={i}>
                    <td>{m.requirement}</td>
                    <td><span className={`badge ${m.covered ? "ok" : "bad"}`}>{m.covered ? "yes" : "no evidence"}</span></td>
                    <td className="small">{m.evidence.length === 0 ? <span className="muted">Nothing in your portfolio proves this, so the proposal will not claim it.</span> :
                      m.evidence.slice(0, 2).map((e: any) => <div key={e.id}><strong>{e.title}</strong> <span className="muted">({e.type.replace("_", " ")}, {e.date || "n.d."})</span><div className="muted">{e.snippet.slice(0, 150)}...</div></div>)}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </div>
          {j.run_id && !working && <p className="small"><Link href={`/runs/${j.run_id}`}>See how the agents reached this (run trace)</Link></p>}
        </>}
      </State>
    </Shell>
  );
}
