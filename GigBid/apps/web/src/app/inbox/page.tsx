"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Shell, { State, StatusBadge } from "@/components/Shell";
import { api } from "@/lib/api";
import { ago, budgetText, pct, useLoad } from "@/lib/hooks";

const FILTERS: [string, string, string][] = [["all", "All", ""], ["approve", "Needs my approval", "awaiting_approval"], ["working", "In progress", "new,analysing,queued"],
  ["watch", "Watch", "watch"], ["skipped", "Skipped", "skipped,filtered,rejected"], ["sent", "Submitted", "submitted"], ["attention", "Needs attention", "blocked,needs_attention,dead_letter"]];

export default function Inbox() {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("fit");
  const [note, setNote] = useState<string | null>(null);
  const status = FILTERS.find((f) => f[0] === filter)![2];
  const jobs = useLoad(() => api.GET("/api/jobs", { params: { query: { sort, ...(status ? { status } : {}) } } }), [filter, sort], 5000);
  async function scout() {
    const r = await api.POST("/api/jobs/scout");
    setNote(r.error ? "Could not start scouting." : r.data?.detail ?? "Scouting now.");
    jobs.reload();
  }
  return (
    <Shell title="Job inbox" sub="Every job the Scout found, with fit, risk and a recommended action." actions={<button onClick={scout}>Scout now</button>}>
      {note && <div className="banner info" role="status">{note}</div>}
      <div className="row spread" style={{ marginBottom: 12 }}>
        <div className="row" role="group" aria-label="Filter jobs">
          {FILTERS.map(([id, label]) => <button key={id} className="chip" aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}
        </div>
        <div className="row"><label htmlFor="sort" style={{ margin: 0 }}>Sort</label>
          <select id="sort" className="inline" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="fit">Best fit</option><option value="recent">Most recent</option><option value="budget">Budget</option><option value="risk">Highest risk</option>
          </select></div>
      </div>
      <State loading={jobs.loading} error={jobs.error} empty={jobs.data?.length === 0 && (filter === "all" ? "No jobs yet. The Scout runs your saved searches every few minutes - or press \"Scout now\"." : "No jobs match this filter.")}>
        <div className="card tablewrap" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Job</th><th>Budget</th><th>Fit</th><th>Risk</th><th>Recommended</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>
              {jobs.data?.map((j) => (
                <tr key={j.job_id} className="click" onClick={() => router.push(`/jobs/${j.job_id}`)} style={{ cursor: "pointer" }}>
                  <td><Link href={`/jobs/${j.job_id}`} onClick={(e) => e.stopPropagation()}><strong>{j.title}</strong></Link>
                    <div className="small muted">{j.category.replace(/_/g, " ")}{j.note ? ` - ${j.note}` : j.reasons?.[0] ? ` - ${j.reasons[0]}` : ""}</div></td>
                  <td className="small">{budgetText(j.budget)}<div className="muted">{j.connects_cost ?? "-"} Connects</div></td>
                  <td>{j.fit == null ? <span className="muted">-</span> : <><span className="meter" aria-hidden="true"><span style={{ width: `${j.fit * 100}%` }} /></span>{pct(j.fit)}</>}</td>
                  <td>{j.risk == null ? <span className="muted">-</span> : <span className={`badge ${j.risk >= 0.6 ? "bad" : j.risk >= 0.3 ? "warn" : "ok"}`}>{j.risk >= 0.6 ? "high" : j.risk >= 0.3 ? "medium" : "low"}</span>}
                    <div className="small muted">{(j.flags ?? []).slice(0, 2).map((f) => f.replace(/_/g, " ")).join(", ")}</div></td>
                  <td>{j.action ? <span className={`badge ${j.action === "bid" ? "ok" : j.action === "watch" ? "warn" : ""}`}>{j.action}</span> : <span className="muted">-</span>}</td>
                  <td><StatusBadge s={j.status} /></td>
                  <td className="small muted">{ago(j.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </State>
    </Shell>
  );
}
