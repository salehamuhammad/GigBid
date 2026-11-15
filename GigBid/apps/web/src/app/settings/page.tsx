"use client";
import { useEffect, useRef, useState } from "react";
import Shell, { State } from "@/components/Shell";
import { api, auth, errorText, type S } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

export default function Settings() {
  const profile = useLoad(() => api.GET("/api/profile"));
  const searches = useLoad(() => api.GET("/api/searches"));
  const memory = useLoad(() => api.GET("/api/memory"));
  const items = useLoad(() => api.GET("/api/portfolio/items"));
  const [s, setS] = useState<S["Settings"] | null>(null);
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);
  const [q, setQ] = useState(""); const [cat, setCat] = useState("");
  const file = useRef<HTMLInputElement>(null); const [docType, setDocType] = useState("case_study");
  useEffect(() => { if (profile.data && !s) setS(profile.data.settings); }, [profile.data, s]);
  const say = (e: unknown, ok: string) => setMsg(e ? { kind: "bad", text: errorText(e) } : { kind: "ok", text: ok });
  const set = <K extends keyof S["Settings"]>(k: K, v: S["Settings"][K]) => setS((x) => (x ? { ...x, [k]: v } : x));

  async function save(e: React.FormEvent) { e.preventDefault(); if (!s) return; const r = await api.PUT("/api/profile", { body: s }); say(r.error, "Settings saved."); profile.reload(); }
  async function connectUpwork() { const r = await api.GET("/api/auth/upwork/start"); if (r.error) return say(r.error, ""); window.location.href = (r.data as { authorize_url: string }).authorize_url; }
  async function disconnectUpwork() { const r = await api.DELETE("/api/auth/upwork"); say(r.error, "Upwork disconnected and stored tokens deleted."); profile.reload(); }
  async function addSearch(e: React.FormEvent) { e.preventDefault(); const r = await api.POST("/api/searches", { body: { query: q, category: cat || null, interval_minutes: 5 } }); say(r.error, "Saved search added."); setQ(""); setCat(""); searches.reload(); }
  async function delSearch(id: string) { const r = await api.DELETE("/api/searches/{search_id}", { params: { path: { search_id: id } } }); say(r.error, "Saved search removed."); searches.reload(); }
  async function delMemory(kind: string, key: string) { const r = await api.DELETE("/api/memory/{kind}/{key}", { params: { path: { kind, key } } }); say(r.error, "Memory item deleted."); memory.reload(); }
  async function delItem(id: string) { const r = await api.DELETE("/api/portfolio/items/{item_id}", { params: { path: { item_id: id } } }); say(r.error, r.data?.detail || "Removed."); items.reload(); }
  async function upload(e: React.FormEvent) {
    e.preventDefault(); const f = file.current?.files?.[0]; if (!f) return say({ detail: "Choose a file first." }, "");
    const fd = new FormData(); fd.append("file", f); fd.append("doc_type", docType);
    const r = await fetch("/api/portfolio/upload", { method: "POST", body: fd, headers: { Authorization: `Bearer ${auth.get()}` } });
    say(r.ok ? null : await r.json().catch(() => ({ detail: "Upload failed" })), "Added and indexed. Only this document was embedded."); items.reload(); if (file.current) file.current.value = "";
  }
  const rules = memory.data?.filter((m) => m.kind === "style" || m.kind === "outcome") ?? [];
  const candidates = memory.data?.filter((m) => m.kind === "style_candidates") ?? [];
  return (
    <Shell title="Settings" sub="Rates, budget, autonomy, connected accounts, saved searches, portfolio and what GigBid has learned about you.">
      {msg && <div className={`banner ${msg.kind}`} role="status">{msg.text}</div>}
      <State loading={profile.loading} error={profile.error}>
        {s && <form className="card" onSubmit={save} aria-labelledby="h-rates">
          <h2 id="h-rates">Rates, budget and autonomy</h2>
          <div className="grid3">
            <div className="field"><label htmlFor="floor">Floor rate ($/h)</label><input id="floor" type="number" min={1} value={s.floor_rate} onChange={(e) => set("floor_rate", +e.target.value)} /></div>
            <div className="field"><label htmlFor="target">Target rate ($/h)</label><input id="target" type="number" min={1} value={s.target_rate} onChange={(e) => set("target_rate", +e.target.value)} /></div>
            <div className="field"><label htmlFor="minp">Smallest project ($)</label><input id="minp" type="number" min={0} value={s.min_project} onChange={(e) => set("min_project", +e.target.value)} /></div>
            <div className="field"><label htmlFor="cb">Weekly Connects budget</label><input id="cb" type="number" min={0} value={s.connects_budget_week} onChange={(e) => set("connects_budget_week", +e.target.value)} /></div>
            <div className="field"><label htmlFor="auto">Autonomy</label><select id="auto" value={s.autonomy} onChange={(e) => set("autonomy", e.target.value as S["Settings"]["autonomy"])}>
              <option value="suggest">Suggest only</option><option value="auto_skip">Auto-skip poor matches</option></select><div className="small muted">Auto-send does not exist.</div></div>
            <div className="field"><label htmlFor="strat">Opening strategy</label><select id="strat" value={s.strategy} onChange={(e) => set("strategy", e.target.value as S["Settings"]["strategy"])}>
              <option value="evidence_first">Lead with a past project</option><option value="question_first">Lead with a question</option></select></div>
          </div>
          <button className="primary">Save settings</button>
        </form>}
        <div className="grid2">
          <section className="card" aria-labelledby="h-acc"><h2 id="h-acc">Connected accounts</h2>
            <p><strong>GigSim simulator</strong> <span className="badge ok">connected</span></p>
            <p><strong>Upwork (live)</strong> {profile.data?.upwork_connected ? <span className="badge ok">connected</span> : <span className="badge">not connected</span>}</p>
            <p className="small muted">Live mode uses Upwork&apos;s official MCP server with OAuth. GigBid reads jobs and creates drafts only; you confirm every draft on Upwork yourself. Tokens are stored encrypted.</p>
            {profile.data?.upwork_connected ? <button className="danger" onClick={disconnectUpwork}>Disconnect Upwork</button> : <button onClick={connectUpwork}>Connect Upwork</button>}
          </section>
          <section className="card" aria-labelledby="h-search"><h2 id="h-search">Saved searches</h2>
            <State loading={searches.loading} error={searches.error} empty={searches.data?.length === 0 && "No saved searches. Add one below."}>
              <ul>{searches.data?.map((x) => <li key={x.id}>{x.query || "any keywords"} <span className="muted">in {x.category?.replace(/_/g, " ") || "all categories"}, every {x.interval_minutes} min</span> <button className="link" onClick={() => delSearch(x.id)} aria-label={`Remove search ${x.query} ${x.category}`}>remove</button></li>)}</ul>
            </State>
            <form className="row" onSubmit={addSearch}><input className="inline" aria-label="Keywords" placeholder="keywords" value={q} onChange={(e) => setQ(e.target.value)} />
              <input className="inline" aria-label="Category" placeholder="category (optional)" value={cat} onChange={(e) => setCat(e.target.value)} /><button>Add</button></form>
          </section>
        </div>
        <section className="card" aria-labelledby="h-mem"><h2 id="h-mem">What GigBid has learned</h2>
          <p className="small muted">Style rules come from your own edits and are only adopted after the same edit is seen in three different drafts. Outcome hints need at least five proposals in a category. Delete anything you disagree with.</p>
          <State loading={memory.loading} error={memory.error} empty={rules.length === 0 && candidates.length === 0 && "Nothing learned yet. Edit a few drafts and rules will appear here."}>
            {rules.length > 0 && <table><thead><tr><th>Rule in use</th><th>Type</th><th>Why it was adopted</th><th></th></tr></thead><tbody>
              {rules.map((m) => <tr key={m.kind + m.key}><td><strong>{m.description}</strong></td><td>{m.kind}</td><td className="small muted">{m.rule}</td><td><button className="danger" onClick={() => delMemory(m.kind, m.key)}>Delete</button></td></tr>)}</tbody></table>}
            {candidates.length > 0 && <><h3 style={{ marginTop: 12 }}>Seen but not adopted yet</h3><ul className="small">{candidates.map((m) => <li key={m.key}>{m.description} <span className="muted">- seen in {(m.value?.drafts as unknown[] | undefined)?.length ?? 0} edit(s)</span> <button className="link" onClick={() => delMemory(m.kind, m.key)}>forget</button></li>)}</ul></>}
          </State>
        </section>
        <section className="card" aria-labelledby="h-port"><h2 id="h-port">Portfolio ({items.data?.length ?? 0} items)</h2>
          <form className="row" onSubmit={upload} style={{ marginBottom: 10 }}>
            <label htmlFor="file" style={{ margin: 0 }}>Add a document</label><input id="file" ref={file} className="inline" type="file" accept=".md,.txt,.pdf" />
            <select className="inline" aria-label="Document type" value={docType} onChange={(e) => setDocType(e.target.value)}><option value="case_study">Case study</option><option value="review">Client review</option><option value="upload">CV / other</option></select>
            <button>Upload and index</button></form>
          <State loading={items.loading} error={items.error} empty={items.data?.length === 0 && "Your portfolio is empty. Upload a CV or case study so GigBid has evidence to cite."}>
            <div className="tablewrap" style={{ maxHeight: 340, overflowY: "auto" }}><table><thead><tr><th>Title</th><th>Type</th><th>Skills</th><th>Date</th><th></th></tr></thead><tbody>
              {items.data?.map((d) => <tr key={String(d.id)}><td>{String(d.title)}</td><td>{String(d.type).replace("_", " ")}</td><td className="small muted">{(d.skills as string[]).slice(0, 5).join(", ")}</td><td className="small">{String(d.date)}</td>
                <td><button className="link" onClick={() => delItem(String(d.id))} aria-label={`Remove ${d.title}`}>remove</button></td></tr>)}</tbody></table></div>
          </State>
        </section>
      </State>
    </Shell>
  );
}
