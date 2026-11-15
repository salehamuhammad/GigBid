"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, auth, errorText } from "@/lib/api";

export default function SignIn() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null);
    const r = await api.POST(mode === "login" ? "/api/auth/login" : "/api/auth/register", { body: { email, password, name } }).catch(() => null);
    setBusy(false);
    if (!r) return setErr("Cannot reach the GigBid API.");
    if (r.error || !r.data) return setErr(errorText(r.error));
    auth.set(r.data.token);
    router.replace(r.data.user.onboarded ? "/inbox" : "/onboarding");
  }
  return (
    <main className="center" id="main">
      <h1>GigBid</h1>
      <p className="muted">Finds freelance jobs, drafts bids grounded in your real portfolio, and asks before it sends anything.</p>
      {process.env.NEXT_PUBLIC_FREE_PREVIEW === "true" && (
        <div className="banner warn" role="note">
          Free preview · Explore with the sample personas and simulated clients. Uses deterministic demo models. Accounts and data reset when the server restarts.
        </div>
      )}
      <form className="card" onSubmit={submit}>
        <h2>{mode === "login" ? "Sign in" : "Create your account"}</h2>
        {err && <div className="banner bad" role="alert">{err}</div>}
        {mode === "register" && <div className="field"><label htmlFor="name">Name</label><input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></div>}
        <div className="field"><label htmlFor="email">Email</label><input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></div>
        <div className="field"><label htmlFor="password">Password</label>
          <input id="password" type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} />
          {mode === "register" && <div className="small muted">At least 8 characters.</div>}</div>
        <button className="primary" disabled={busy}>{busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}</button>
      </form>
      <button className="link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(null); }}>
        {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
      </button>
    </main>
  );
}
