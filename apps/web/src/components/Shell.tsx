"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, auth } from "@/lib/api";
import { useLoad } from "@/lib/hooks";

const NAV = [["/inbox", "Job inbox"], ["/pipeline", "Pipeline"], ["/messages", "Messages"], ["/runs", "Agent runs"], ["/analytics", "Analytics"], ["/settings", "Settings"]] as const;

/** App frame: navigation, pending-approval count and the degraded-mode banner (never a blank screen). */
export default function Shell({ title, sub, actions, children }: { title: string; sub?: string; actions?: React.ReactNode; children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  useEffect(() => { if (!auth.get()) router.replace("/signin"); else setReady(true); }, [router]);
  const health = useLoad(() => api.GET("/api/system/health"), [], 15000);
  const pending = useLoad(() => api.GET("/api/approvals", { params: { query: { status: "pending" } } }), [], 6000);
  if (!ready) return <main className="center muted" aria-busy="true">Loading...</main>;
  const h = health.data;
  const n = pending.data?.length ?? 0;
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="brand">GigBid</div>
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} aria-current={path.startsWith(href) ? "page" : undefined}>
            {label}
            {href === "/inbox" && n > 0 && <span className="badge info" aria-label={`${n} waiting for approval`}>{n}</span>}
          </Link>
        ))}
        <div className="foot">
          {h && <div>{h.marketplace_mode === "upwork" ? "Live: Upwork" : "Simulator: GigSim"}<br />Models: {h.model_profile}<br />Worker: {h.worker}</div>}
          <button className="link" onClick={() => { auth.clear(); router.replace("/signin"); }}>Sign out</button>
        </div>
      </nav>
      <main className="main" id="main">
        {process.env.NEXT_PUBLIC_FREE_PREVIEW === "true" && (
          <div className="banner warn" role="note">
            Free preview · Deterministic demo models and simulated clients. Accounts, uploads and progress reset when the server restarts.
          </div>
        )}
        <div role="status" aria-live="polite">
          {health.error && <div className="banner bad">The GigBid API is not reachable. Your data is safe; this page will recover on its own.</div>}
          {h && h.status === "degraded" && (
            <div className="banner warn">
              <strong>Marketplace unavailable.</strong> New work is queued and will resume automatically{h.queued_jobs ? ` (${h.queued_jobs} job${h.queued_jobs > 1 ? "s" : ""} queued)` : ""}. Nothing is lost and nothing is sent twice.
              <span className="small muted"> {String(h.marketplace?.detail || "").slice(0, 140)}</span>
            </div>
          )}
        </div>
        <div className="head">
          <div><h1>{title}</h1>{sub && <div className="muted">{sub}</div>}</div>
          <div className="row">{actions}</div>
        </div>
        {children}
      </main>
    </div>
  );
}

export function State({ loading, error, empty, children }: { loading: boolean; error: string | null; empty?: string | false; children: React.ReactNode }) {
  if (loading) return <div className="card empty" aria-busy="true">Loading...</div>;
  if (error) return <div className="banner bad" role="alert">{error}</div>;
  if (empty) return <div className="card empty">{empty}</div>;
  return <>{children}</>;
}

export function StatusBadge({ s }: { s: string }) {
  const kind = ["submitted", "hired", "replied", "interview", "approved", "done", "sent"].includes(s) ? "ok"
    : ["awaiting_approval", "waiting_approval", "watch", "queued", "needs_reply", "drafted"].includes(s) ? "warn"
    : ["blocked", "needs_attention", "dead_letter", "failed", "flagged", "lost"].includes(s) ? "bad" : ["analysing", "running"].includes(s) ? "info" : "";
  return <span className={`badge ${kind}`}>{s.replace(/_/g, " ")}</span>;
}
