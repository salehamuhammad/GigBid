"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, auth, errorText, type S } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

/** First run: portfolio, rates and filters, weekly Connects budget, marketplace. */
export default function Onboarding() {
  const router = useRouter();
  useEffect(() => { if (!auth.get()) router.replace("/signin"); }, [router]);
  const personas = useLoad(() => api.GET("/api/personas"));
  const [persona, setPersona] = useState<string>("");
  const [s, setS] = useState<S["Settings"]>({ floor_rate: 30, target_rate: 45, min_project: 200, connects_budget_week: 60, autonomy: "suggest", strategy: "evidence_first", experiment: false, categories: [], min_budget: 0, marketplace: "gigsim", onboarded: true });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const chosen = personas.data?.find((p) => p.id === persona);
  const set = <K extends keyof S["Settings"]>(k: K, v: S["Settings"][K]) => setS((x) => ({ ...x, [k]: v }));

  function pick(id: string) {
    setPersona(id);
    const p = personas.data?.find((x) => x.id === id);
    if (p) setS((x) => ({ ...x, floor_rate: p.floor_rate, target_rate: p.target_rate, min_project: p.min_project, categories: p.categories }));
    else setS((x) => ({ ...x, categories: [] }));
  }
  async function finish(e: React.FormEvent) {
    e.preventDefault();
    if (!persona) return setErr("Choose a portfolio to start with.");
    if (s.target_rate < s.floor_rate) return setErr("Your target rate cannot be below your floor rate.");
    setBusy(true); setErr(null);
    const r = await api.POST("/api/profile/onboard", { body: { persona, settings: s } });
    setBusy(false);
    if (r.error) return setErr(errorText(r.error));
    router.replace("/inbox");
  }
  return (
    <main className="main" id="main" style={{ margin: "0 auto", maxWidth: 860 }}>
      <h1>Set up GigBid</h1>
      <p className="muted">Three short steps. You can change all of this later in Settings.</p>
      <form onSubmit={finish}>
        <section className="card" aria-labelledby="s1">
          <h2 id="s1">1. Your portfolio</h2>
          <p className="small muted">GigBid only ever claims experience it can find here. Start from a bundled sample portfolio (synthetic data) or an empty one you upload into from Settings.</p>
          {personas.loading ? <div className="muted">Loading portfolios...</div> : personas.error ? <div className="banner bad">{personas.error}</div> : (
            <div className="grid2">
              {personas.data?.map((p) => (
                <button type="button" key={p.id} className="pick" aria-pressed={persona === p.id} onClick={() => pick(p.id)}>
                  <strong>{p.name}</strong><div className="small">{p.headline}</div><div className="small muted">{p.skills.slice(0, 7).join(", ")}...</div>
                </button>
              ))}
              <button type="button" className="pick" aria-pressed={persona === "own"} onClick={() => pick("own")}>
                <strong>My own portfolio</strong><div className="small">Start empty and upload your CV, case studies and reviews.</div>
              </button>
            </div>
          )}
        </section>
        <section className="card" aria-labelledby="s2">
          <h2 id="s2">2. Rates and filters</h2>
          <div className="grid3">
            <div className="field"><label htmlFor="floor">Floor rate ($/h)</label><input id="floor" type="number" min={1} value={s.floor_rate} onChange={(e) => set("floor_rate", +e.target.value)} /><div className="small muted">GigBid never bids below this.</div></div>
            <div className="field"><label htmlFor="target">Target rate ($/h)</label><input id="target" type="number" min={1} value={s.target_rate} onChange={(e) => set("target_rate", +e.target.value)} /></div>
            <div className="field"><label htmlFor="minp">Smallest project ($)</label><input id="minp" type="number" min={0} value={s.min_project} onChange={(e) => set("min_project", +e.target.value)} /></div>
          </div>
          {chosen && <div className="small muted">Saved searches will be created for: {chosen.categories.join(", ")}</div>}
        </section>
        <section className="card" aria-labelledby="s3">
          <h2 id="s3">3. Budget and marketplace</h2>
          <div className="grid2">
            <div className="field"><label htmlFor="cb">Weekly Connects budget</label><input id="cb" type="number" min={0} value={s.connects_budget_week} onChange={(e) => set("connects_budget_week", +e.target.value)} /><div className="small muted">GigBid stops recommending bids when this is used up.</div></div>
            <div className="field"><label htmlFor="auto">Autonomy</label>
              <select id="auto" value={s.autonomy} onChange={(e) => set("autonomy", e.target.value as S["Settings"]["autonomy"])}>
                <option value="suggest">Suggest only - show me everything</option><option value="auto_skip">Auto-skip poor matches</option>
              </select><div className="small muted">There is no auto-send. Every proposal and message waits for your approval.</div></div>
          </div>
          <div className="banner info small">Marketplace: <strong>GigSim simulator</strong>. You can connect a real Upwork account later in Settings; live mode only ever creates drafts.</div>
        </section>
        {err && <div className="banner bad" role="alert">{err}</div>}
        <button className="primary" disabled={busy}>{busy ? "Setting up and scouting jobs..." : "Finish and open my inbox"}</button>
      </form>
    </main>
  );
}
