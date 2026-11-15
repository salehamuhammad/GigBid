"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import RunStream from "@/components/RunStream";
import Shell, { State, StatusBadge } from "@/components/Shell";
import { api, errorText, type S } from "@/lib/api";
import { money, useLoad } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Claim = { text: string; label: string; evidence_ids: string[]; reason?: string };

/** The draft with the evidence behind every claim shown on hover / focus (D5). */
function Letter({ text, claims, evidence }: { text: string; claims: Claim[]; evidence: Record<string, any> }) {
  const parts: React.ReactNode[] = []; let rest = text; let k = 0;
  for (const c of claims) {
    const i = rest.indexOf(c.text);
    if (i < 0) continue;
    if (i > 0) parts.push(rest.slice(0, i));
    if (c.label === "not_a_claim") parts.push(c.text);
    else parts.push(
      <span key={k++} className={`claim ${c.label}`} tabIndex={0} aria-label={`${c.text} Claim is ${c.label.replace("_", " ")}.`}>
        {c.text}
        <span className="pop" role="tooltip">
          <strong>{c.label.replace("_", " ")}</strong>{c.reason ? ` - ${c.reason}` : ""}
          {c.evidence_ids.map((id) => evidence[id] && (
            <span key={id} style={{ display: "block", marginTop: 6 }}>
              <strong>{evidence[id].title}</strong> <span className="muted">({String(evidence[id].type).replace("_", " ")}, {evidence[id].date || "n.d."})</span>
              <span className="muted" style={{ display: "block" }}>{String(evidence[id].text).replace(/[#*]/g, "").slice(0, 260)}...</span>
            </span>))}
          {c.evidence_ids.length === 0 && <span className="muted" style={{ display: "block" }}>No evidence item is attached to this sentence.</span>}
        </span>
      </span>);
    rest = rest.slice(i + c.text.length);
  }
  parts.push(rest);
  return <div className="letter" data-testid="letter">{parts}</div>;
}

export default function Studio() {
  const { id } = useParams<{ id: string }>();
  const job = useLoad(() => api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }), [id], 3000);
  const j = job.data;
  const ap = useLoad<any>(() => (j?.approval_id ? (api.GET("/api/approvals/{approval_id}", { params: { path: { approval_id: j.approval_id } } }) as any) : Promise.resolve({ data: undefined, response: new Response() } as any)), [j?.approval_id]);
  const p: any = j?.approval_id ? ap.data?.payload : null;
  const draft: any = p?.draft ?? j?.proposal?.draft;
  const [editing, setEditing] = useState(false); const [text, setText] = useState(""); const [bid, setBid] = useState<string>("");
  const [reason, setReason] = useState(""); const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);
  useEffect(() => { if (draft && !editing) { setText(draft.cover_letter); setBid(String(p?.price?.bid_amount ?? j?.price ?? "")); } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [draft?.cover_letter, p?.price?.bid_amount]);

  async function decide(body: S["DecisionIn"]) {
    if (!j?.approval_id) return;
    setBusy(true); setMsg(null);
    const r = await api.POST("/api/approvals/{approval_id}/decision", { params: { path: { approval_id: j.approval_id } }, body });
    setBusy(false); setEditing(false); setRejecting(false);
    setMsg(r.error ? { kind: "bad", text: errorText(r.error) } : { kind: "info", text: r.data?.detail || "Done" });
    setTimeout(() => { job.reload(); }, 600);
  }
  const working = j && ["analysing", "new", "queued"].includes(j.status);
  const paragraphs: string[] = draft ? String(draft.cover_letter).split(/\n\n+/) : [];
  const critique = p?.critique; const comp = p?.compliance; const ver = p?.verification; const prev = p?.preview;
  return (
    <Shell title="Proposal studio" sub={j?.title} actions={j && <StatusBadge s={j.status} />}>
      <p><Link href={`/jobs/${id}`}>&larr; Job detail</Link></p>
      {msg && <div className={`banner ${msg.kind}`} role="status">{msg.text}</div>}
      <State loading={job.loading} error={job.error} empty={!job.loading && !draft && !working && "There is no draft for this job. GigBid only drafts for jobs it recommends bidding on."}>
        {working && <RunStream runId={j?.run_id} onDone={job.reload} />}
        {j?.status === "blocked" && <div className="banner bad" role="alert"><strong>Blocked by Compliance.</strong> {j.note}</div>}
        {j?.status === "submitted" && <div className="banner ok">Submitted. Track it on the <Link href="/pipeline">pipeline board</Link>.</div>}
        {j?.status === "awaiting_upwork" && <div className="banner warn" role="status">Draft created on Upwork. Review and confirm it there.</div>}
        {draft && (
          <div className="grid2" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(280px, 1fr)" }}>
            <div>
              <div className="card">
                <div className="row spread"><h2>Cover letter</h2>
                  {p && !editing && <button onClick={() => setEditing(true)}>Edit</button>}</div>
                {p?.warnings?.map((w: string, i: number) => <div key={i} className="note">{w}</div>)}
                {critique?.verdict === "revise" && <div className="note"><strong>Critic:</strong> {critique.reasons.join("; ")}</div>}
                {editing ? (
                  <>
                    <label htmlFor="edit">Edit the draft</label>
                    <textarea id="edit" value={text} onChange={(e) => setText(e.target.value)} />
                    <div className="small muted">Your edit is compared with the draft, re-checked by Compliance, and repeated edits become style rules.</div>
                    <div className="row" style={{ marginTop: 8 }}>
                      <button className="primary" disabled={busy || !text.trim()} onClick={() => decide({ action: "edit", edited_text: text, edited_bid: +bid || undefined })}>Save edit and re-check</button>
                      <button onClick={() => setEditing(false)}>Cancel</button>
                    </div>
                  </>
                ) : <Letter text={draft.cover_letter} claims={draft.claims || []} evidence={p?.evidence || {}} />}
                {!editing && <div className="small muted" style={{ marginTop: 10 }}>
                  <span className="claim supported">Underlined green</span> is proven by your portfolio, <span className="claim partly_supported">amber</span> is partly supported. Hover or tab to a sentence to see its evidence. {String(draft.cover_letter).split(/\s+/).length} words.
                </div>}
                {p && !editing && paragraphs.length > 1 && <div className="row" style={{ marginTop: 10 }}>
                  <span className="small muted">Regenerate:</span>
                  {paragraphs.map((_, i) => <button key={i} className="chip" disabled={busy} onClick={() => decide({ action: "regenerate", paragraph: i })}>paragraph {i + 1}</button>)}
                </div>}
              </div>
              {draft.screening_answers?.length > 0 && <div className="card"><h2>Screening answers</h2>
                {draft.screening_answers.map((a: any, i: number) => <div key={i} style={{ marginBottom: 10 }}><strong>{a.question}</strong><div>{a.answer}</div></div>)}</div>}
              {p?.edit_diff?.unified && <div className="card"><h2>Your last edit</h2><div className="diff">
                {String(p.edit_diff.unified).split("\n").slice(2).map((l: string, i: number) => <div key={i} className={l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : ""}>{l}</div>)}</div></div>}
            </div>
            <div>
              {p ? (
                <div className="card" aria-labelledby="approve-h">
                  <h2 id="approve-h">Approve this proposal?</h2>
                  <div className="field"><label htmlFor="bid">Bid ({p.price.bid_type === "hourly" ? "$/hour" : "$ total"})</label>
                    <input id="bid" type="number" min={1} value={bid} onChange={(e) => setBid(e.target.value)} /></div>
                  <table><tbody>
                    <tr><td>Connects this will spend</td><td><strong>{prev?.connects?.total ?? p.price.connects_cost}</strong>{prev?.connects?.surcharge ? <span className="small muted"> (incl. {prev.connects.surcharge} surcharge)</span> : null}</td></tr>
                    <tr><td>Balance after</td><td>{prev?.balance_after ?? "-"}</td></tr>
                    <tr><td>Risk</td><td><span className={`badge ${p.risk.level === "high" ? "bad" : p.risk.level === "medium" ? "warn" : "ok"}`}>{p.risk.level}</span></td></tr>
                    <tr><td>Claims checked</td><td>{ver ? `${ver.total_claims} (${ver.unsupported_before} unsupported removed)` : "-"}</td></tr>
                    <tr><td>Compliance</td><td><span className={`badge ${comp?.status === "pass" ? "ok" : "warn"}`}>{comp?.status}</span></td></tr>
                  </tbody></table>
                  {comp?.reason && <div className="note" style={{ marginTop: 8 }}>{comp.reason}</div>}
                  <details style={{ margin: "10px 0" }}><summary className="small">Why this price</summary><ul className="small">{p.price.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></details>
                  <details style={{ margin: "10px 0" }}><summary className="small">Exactly what will be sent (dry run)</summary><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(prev?.would_send, null, 1)}</pre></details>
                  {rejecting ? (
                    <>
                      <div className="field"><label htmlFor="why">Why are you rejecting it?</label><input id="why" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. client budget is too low" /></div>
                      <div className="row"><button className="danger" disabled={busy || !reason.trim()} onClick={() => decide({ action: "reject", reason })}>Confirm reject</button><button onClick={() => setRejecting(false)}>Cancel</button></div>
                    </>
                  ) : (
                    <div className="row">
                      <button className="primary" disabled={busy || editing} onClick={() => decide(+bid && +bid !== p.price.bid_amount ? { action: "edit", edited_text: draft.cover_letter, edited_bid: +bid } : { action: "approve" })}>
                        {+bid && +bid !== p.price.bid_amount ? "Update bid and re-check" : `Approve and submit (${prev?.connects?.total ?? p.price.connects_cost} Connects)`}</button>
                      <button className="danger" disabled={busy} onClick={() => setRejecting(true)}>Reject</button>
                    </div>
                  )}
                  <div className="small muted" style={{ marginTop: 8 }}>Nothing is sent and no Connects are spent until you approve.</div>
                </div>
              ) : (
                <div className="card"><h2>Status</h2><p>{j?.proposal ? `This proposal is ${j.proposal.stage}.` : "No approval is pending."}</p>{j?.proposal?.bid ? <p>Bid: {money(Number(j.proposal.bid))}</p> : null}</div>
              )}
              {j?.run_id && <p className="small"><Link href={`/runs/${j.run_id}`}>Run trace for this draft</Link></p>}
            </div>
          </div>
        )}
      </State>
    </Shell>
  );
}
