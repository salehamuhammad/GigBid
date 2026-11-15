"use client";
import Link from "next/link";
import Shell, { State } from "@/components/Shell";
import { api } from "@/lib/api";
import { ago, money, useLoad } from "@/lib/hooks";

const STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"];

export default function Pipeline() {
  const props = useLoad(() => api.GET("/api/proposals"), [], 6000);
  const rejected = props.data?.filter((p) => p.stage === "rejected") ?? [];
  return (
    <Shell title="Pipeline" sub="Every proposal from draft to outcome. Stages update as the marketplace reports events.">
      <State loading={props.loading} error={props.error} empty={props.data?.length === 0 && "No proposals yet. Approve a draft from the inbox and it will appear here."}>
        <div className="board" role="list" aria-label="Pipeline board">
          {STAGES.map((st) => {
            const items = props.data?.filter((p) => p.stage === st) ?? [];
            return (
              <section key={st} className="col" role="listitem" aria-label={`${st}: ${items.length}`}>
                <h3>{st}<span className="badge">{items.length}</span></h3>
                {items.map((p) => (
                  <div key={p.id} className="tile">
                    <Link href={p.stage === "drafted" ? `/studio/${p.job_id}` : `/jobs/${p.job_id}`}><strong>{p.title}</strong></Link>
                    <div className="muted">{money(p.bid)} - {p.connects} Connects</div>
                    <div className="muted">{ago(p.updated_at)}{p.conversation_id && ["replied", "interview", "hired"].includes(p.stage) ? <> - <Link href="/messages">messages</Link></> : null}</div>
                  </div>))}
              </section>);
          })}
        </div>
        {rejected.length > 0 && <div className="card" style={{ marginTop: 14 }}><h2>Rejected by you</h2>
          <ul>{rejected.map((p) => <li key={p.id}><Link href={`/jobs/${p.job_id}`}>{p.title}</Link> <span className="muted">- {p.reject_reason}</span></li>)}</ul></div>}
      </State>
    </Shell>
  );
}
