"use client";
import { useEffect, useState } from "react";
import Shell, { State, StatusBadge } from "@/components/Shell";
import { api, errorText, type S } from "@/lib/api";
import { ago, useLoad } from "@/lib/hooks";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function Messages() {
  const convs = useLoad(() => api.GET("/api/conversations"), [], 5000);
  const [sel, setSel] = useState<string | null>(null);
  const [text, setText] = useState(""); const [editing, setEditing] = useState(false); const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const c = convs.data?.find((x) => x.conversation_id === sel) ?? convs.data?.[0];
  const p: any = c?.approval?.payload;
  useEffect(() => { if (p && !editing) setText(p.reply.text); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [p?.reply?.text]);
  async function decide(body: S["DecisionIn"]) {
    if (!c?.approval) return;
    setBusy(true);
    const r = await api.POST("/api/approvals/{approval_id}/decision", { params: { path: { approval_id: c.approval.id } }, body });
    setBusy(false); setEditing(false); setMsg(r.error ? errorText(r.error) : r.data?.detail || "Done"); setTimeout(convs.reload, 700);
  }
  async function draft() {
    if (!c) return;
    const r = await api.POST("/api/conversations/{conversation_id}/draft", { params: { path: { conversation_id: c.conversation_id } } });
    setMsg(r.error ? errorText(r.error) : "Drafting a reply..."); setTimeout(convs.reload, 1500);
  }
  return (
    <Shell title="Messages" sub="Client replies, what each one is asking for, and a draft response waiting for your approval.">
      {msg && <div className="banner info" role="status">{msg}</div>}
      <State loading={convs.loading} error={convs.error} empty={convs.data?.length === 0 && "No client conversations yet. They appear here when a client replies to a proposal."}>
        <div className="grid2" style={{ gridTemplateColumns: "minmax(220px, 1fr) minmax(0, 2.4fr)" }}>
          <div className="card" style={{ padding: 6 }}>
            {convs.data?.map((x) => (
              <button key={x.conversation_id} className="pick" style={{ border: 0, marginBottom: 2 }} aria-pressed={c?.conversation_id === x.conversation_id} onClick={() => { setSel(x.conversation_id); setEditing(false); }}>
                <strong>{x.title || x.job_id}</strong>
                <div className="row small"><StatusBadge s={x.status} />{x.intent && <span className={`badge ${x.intent === "scam_signal" ? "bad" : "info"}`}>{x.intent.replace("_", " ")}</span>}<span className="muted">{ago(x.updated_at)}</span></div>
              </button>))}
          </div>
          {c && (
            <div>
              <div className="card">
                <h2>{c.title || c.job_id}</h2>
                {c.intent === "scam_signal" && <div className="banner bad" role="alert"><strong>Possible scam.</strong> The client asked to move contact or payment off the platform. GigBid will not follow that and suggests the reply below.</div>}
                {c.messages.map((m: any) => <div key={m.id} className={`msg ${m.from}`}><div className="small muted">{m.from === "client" ? "Client" : "You"} - {ago(m.at)}</div>{m.text}</div>)}
                {!c.approval && c.messages.at(-1)?.from === "client" && <button onClick={draft}>Draft a reply</button>}
              </div>
              {p && (
                <div className="card" aria-labelledby="reply-h">
                  <h2 id="reply-h">Suggested reply <span className="badge info">{String(p.intent.intent).replace("_", " ")}</span></h2>
                  {p.intent.injection_detected && <div className="note">The client&apos;s message contained text aimed at AI tools. It was ignored.</div>}
                  {p.reply.slots?.length > 0 && <div className="small muted">Free slots offered from your calendar: {p.reply.slots.map((s: any) => s.label).join("; ")}. Approving places a tentative hold on the first.</div>}
                  {editing ? <><label htmlFor="rt">Edit reply</label><textarea id="rt" style={{ minHeight: 130 }} value={text} onChange={(e) => setText(e.target.value)} /></> : <div className="msg freelancer" style={{ maxWidth: "100%" }}>{p.reply.text}</div>}
                  {p.compliance?.status !== "pass" && <div className="note">Compliance: {p.compliance?.reason}</div>}
                  <div className="row" style={{ marginTop: 8 }}>
                    {editing ? <><button className="primary" disabled={busy || !text.trim()} onClick={() => decide({ action: "edit", edited_text: text })}>Send edited reply</button><button onClick={() => setEditing(false)}>Cancel</button></> : <>
                      <button className="primary" disabled={busy} onClick={() => decide({ action: "approve" })}>Approve and send</button>
                      <button disabled={busy} onClick={() => setEditing(true)}>Edit</button>
                      <input className="inline" aria-label="Reason for rejecting" placeholder="Reason to reject" value={reason} onChange={(e) => setReason(e.target.value)} />
                      <button className="danger" disabled={busy || !reason.trim()} onClick={() => decide({ action: "reject", reason })}>Reject</button></>}
                  </div>
                  <div className="small muted" style={{ marginTop: 6 }}>Nothing is sent until you approve. Edited replies are re-checked by Compliance first.</div>
                </div>
              )}
            </div>
          )}
        </div>
      </State>
    </Shell>
  );
}
