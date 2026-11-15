"""GigSim: a small freelance-marketplace simulator (REST). Run: uvicorn gigsim.app:app --port 8081

Jobs with duplicates, scams and planted prompt injections; clients with public history and hidden
preferences; Connects; drafts -> submit; message threads; an event feed; rate limits and
occasional 503s. All data is synthetic unless scripts/prepare_kaggle.py merged real rows.
"""
from __future__ import annotations

import os
import random
import statistics
import time
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim.clients import score_proposal
from gigsim.store import Store

app = FastAPI(title="GigSim", version="1.0.0")
store = Store()
_rng = random.Random(1234)
TOKEN = os.getenv("GIGSIM_API_TOKEN", "gigsim-dev-token")


def _error_rate() -> float:
    v = os.getenv("GIGSIM_ERROR_RATE")
    return float(v) if v not in (None, "") else float(store.policy.get("error_rate", 0))


def account(request: Request, authorization: str = Header(default=""), x_account: str = Header(default="default")) -> dict:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "invalid or missing bearer token")
    with store.lock:
        acc = store.account(x_account)
        acc["name"] = x_account
        if not request.url.path.startswith(("/admin", "/eval")):
            now = time.time()
            acc["calls"] = [t for t in acc["calls"] if now - t < 60]
            limit = int(os.getenv("GIGSIM_RATE_LIMIT") or store.policy["rate_limit_per_minute"])
            if len(acc["calls"]) >= limit:
                raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(60 - (now - acc["calls"][0])) + 1)})
            acc["calls"].append(now)
            if _rng.random() < _error_rate():
                raise HTTPException(503, "GigSim is having a moment, retry shortly")
        store.materialize(acc)
        return acc


def _idem(acc: dict, key: str | None, fn):
    """Replay the stored response for a repeated Idempotency-Key."""
    if not key:
        raise HTTPException(400, "Idempotency-Key header is required on writes")
    if key in acc["idem"]:
        return {**acc["idem"][key], "idempotent_replay": True}
    res = fn()
    acc["idem"][key] = res
    store.save()
    return res


def _job(job_id: str) -> dict:
    j = store.jobs.get(job_id)
    if not j:
        raise HTTPException(404, f"job {job_id} not found")
    return j


@app.get("/health")
def health(): return {"status": "ok", "service": "gigsim", "policy_version": store.policy["version"]}


@app.get("/policy")
def policy(acc: dict = Depends(account)): return store.policy


@app.get("/jobs/search")
def search_jobs(q: str = "", category: str | None = None, limit: int = 20, offset: int = 0, acc: dict = Depends(account)):
    terms = [t for t in q.lower().split() if t]
    out = []
    for j in reversed(store.released()):
        hay = (j["title"] + " " + j["description"]).lower()
        if (not terms or any(t in hay for t in terms)) and (not category or j["category"] == category):
            out.append({k: j[k] for k in ("job_id", "title", "category", "budget", "posted_at", "client_id", "connects_cost", "proposals_so_far")} | {"snippet": j["description"][:240]})
    return {"total": len(out), "jobs": out[offset: offset + min(limit, 50)]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, acc: dict = Depends(account)):
    j = _job(job_id)
    return {**j, "connects": store.connects_cost(j)}


@app.get("/clients/{client_id}/history")
def client_history(client_id: str, acc: dict = Depends(account)):
    c = store.clients.get(client_id)
    if not c: raise HTTPException(404, "client not found")
    return c


@app.get("/connects")
def connects(acc: dict = Depends(account)):
    today = time.strftime("%Y-%m-%d")
    return {"balance": acc["connects"], "weekly_allowance": store.policy["connects"]["weekly_allowance"],
            "proposals_today": sum(1 for p in acc["proposals"].values() if p["day"] == today),
            "daily_proposal_cap": store.policy.get("update", {}).get("daily_proposal_cap")}


@app.get("/market/stats")
def market_stats(category: str, acc: dict = Depends(account)):
    rows = [j for j in store.historical if j.get("category") == category]
    fixed = sorted(j["budget"]["max"] for j in rows if j["budget"]["type"] == "fixed" and j["budget"]["max"])
    hourly = sorted((j["budget"]["min"] + j["budget"]["max"]) / 2 for j in rows if j["budget"]["type"] == "hourly" and j["budget"]["max"])
    def q(xs):
        if len(xs) < 4: return None
        qs = statistics.quantiles(xs, n=4)
        return {"p25": round(qs[0], 2), "median": round(qs[1], 2), "p75": round(qs[2], 2), "n": len(xs)}
    per_hour = sorted(j["budget"]["max"] / j["est_hours"] for j in rows if j["budget"]["type"] == "fixed" and j.get("est_hours") and j["budget"]["max"])
    return {"category": category, "n_jobs": len(rows), "fixed_budget_usd": q(fixed), "hourly_rate_usd": q(hourly), "fixed_usd_per_est_hour": q(per_hour),
            "provenance": sorted({j.get("provenance", "synthetic") for j in rows})}


class DraftIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1)
    bid_amount: float = Field(gt=0)
    screening_answers: list[str] = []


@app.post("/proposals/drafts")
def create_draft(body: DraftIn, acc: dict = Depends(account), idempotency_key: str | None = Header(default=None)):
    job = _job(body.job_id)
    maxc = store.policy.get("update", {}).get("max_cover_letter_chars") or store.policy["proposal"]["max_cover_letter_chars"]
    if len(body.cover_letter) > maxc:
        raise HTTPException(422, f"cover letter exceeds {maxc} characters (policy {store.policy['version']})")
    def make():
        d = {"draft_id": "dr-" + uuid.uuid4().hex[:10], **body.model_dump(), "connects": store.connects_cost(job), "status": "draft", "created_at": store.now()}
        acc["drafts"][d["draft_id"]] = d
        return d
    with store.lock: return _idem(acc, idempotency_key, make)


@app.post("/proposals/{draft_id}/submit")
def submit(draft_id: str, acc: dict = Depends(account), idempotency_key: str | None = Header(default=None)):
    def make():
        d = acc["drafts"].get(draft_id)
        if not d: raise HTTPException(404, "draft not found")
        if any(p["job_id"] == d["job_id"] for p in acc["proposals"].values()):
            raise HTTPException(409, "a proposal for this job was already submitted")
        today = time.strftime("%Y-%m-%d")
        cap = store.policy.get("update", {}).get("daily_proposal_cap")
        if cap and sum(1 for p in acc["proposals"].values() if p["day"] == today) >= cap:
            raise HTTPException(409, f"daily proposal cap of {cap} reached (policy {store.policy['version']})")
        cost = d["connects"]["total"]
        if acc["connects"] < cost: raise HTTPException(402, "not enough Connects")
        acc["connects"] -= cost
        job = _job(d["job_id"])
        pid = "pr-" + uuid.uuid4().hex[:10]
        out = score_proposal(job, store.hidden.get(job["job_id"], {}), store.clients.get(job["client_id"], {}), d["cover_letter"], d["bid_amount"], d["screening_answers"], store.lexicon, acc.get("name", "default"))
        p = {"proposal_id": pid, "draft_id": draft_id, "job_id": d["job_id"], "client_id": job["client_id"], "bid_amount": d["bid_amount"], "status": "submitted",
             "connects_spent": cost, "submitted_at": store.now(), "day": today, "thread_id": "th-" + pid[3:]}
        acc["proposals"][pid] = p
        d["status"] = "submitted"
        t, dl = store.now(), store.delay
        hidden = store.hidden.get(job["job_id"], {})
        if out["viewed"]: store.emit(acc, "viewed", t + dl, proposal_id=pid, job_id=job["job_id"])
        if out["replied"]:
            kind = "scam" if hidden.get("kind") == "scam" else "injection" if hidden.get("kind") == "injection" and _rng.random() < 0.5 else "interview" if out["interview"] else _rng.choice(["question", "negotiation"])
            store.emit(acc, "replied", t + 2 * dl, proposal_id=pid, job_id=job["job_id"])
            store.emit(acc, "client_message", t + 2 * dl, thread_id=p["thread_id"], job_id=job["job_id"], client_id=job["client_id"], text=_client_text(kind, job, d, hidden))
            if out["interview"]: store.emit(acc, "interview", t + 4 * dl, proposal_id=pid, job_id=job["job_id"])
            if out["hired"]: store.emit(acc, "hired", t + 6 * dl, proposal_id=pid, job_id=job["job_id"])
        else:
            store.emit(acc, "lost", t + 8 * dl, proposal_id=pid, job_id=job["job_id"])
        return {**p, "connects_balance": acc["connects"]}
    with store.lock: return _idem(acc, idempotency_key, make)


def _client_text(kind: str, job: dict, draft: dict, hidden: dict) -> str:
    tmpl = _rng.choice(store.msgs.get(kind) or ["Thanks for your proposal. Can you tell me more?"])
    skill = (hidden.get("prefs", {}).get("must_have_skills") or ["the main"])[0]
    return tmpl.format(skill=skill, offer=f"${round(draft['bid_amount'] * 0.8)}", canary=hidden.get("canary") or "CANARY-MSG001")


@app.get("/proposals")
def proposals(acc: dict = Depends(account)): return {"proposals": list(acc["proposals"].values())}


@app.get("/threads")
def threads(acc: dict = Depends(account)):
    return {"threads": [{"thread_id": t["thread_id"], "job_id": t["job_id"], "client_id": t["client_id"], "n_messages": len(t["messages"]),
                         "last": t["messages"][-1] if t["messages"] else None} for t in acc["threads"].values()]}


@app.get("/threads/{thread_id}/messages")
def messages(thread_id: str, acc: dict = Depends(account)):
    t = acc["threads"].get(thread_id)
    if not t: raise HTTPException(404, "thread not found")
    return t


class MessageIn(BaseModel):
    thread_id: str
    text: str = Field(min_length=1, max_length=4000)


@app.post("/messages")
def send_message(body: MessageIn, acc: dict = Depends(account), idempotency_key: str | None = Header(default=None)):
    def make():
        t = acc["threads"].get(body.thread_id)
        if not t: raise HTTPException(404, "thread not found")
        m = {"id": "m-" + uuid.uuid4().hex[:10], "from": "freelancer", "text": body.text, "at": store.now()}
        t["messages"].append(m)
        n_client = sum(1 for x in t["messages"] if x["from"] == "client")
        if n_client < 3:  # the simulated client keeps the conversation going for a few turns
            nxt = "interview" if n_client == 1 else "question"
            job = store.jobs.get(t["job_id"], {"job_id": t["job_id"]})
            store.emit(acc, "client_message", store.now() + store.delay, thread_id=t["thread_id"], job_id=t["job_id"], client_id=t["client_id"],
                       text=_client_text(nxt, job, {"bid_amount": 500}, store.hidden.get(t["job_id"], {})))
        return m
    with store.lock: return _idem(acc, idempotency_key, make)


@app.get("/events")
def events(since: int = 0, acc: dict = Depends(account)):
    store.save()
    return {"events": [e for e in acc["events"] if e["seq"] > since], "cursor": acc["cursor"]}


# ---------------------------------------------------------------- admin / evaluation helpers
@app.post("/admin/reset")
def admin_reset(acc: dict = Depends(account)):
    with store.lock: store.reset()
    return {"ok": True}


@app.post("/admin/advance")
def admin_advance(seconds: float = 3600, release: int = 0, acc: dict = Depends(account)):
    """Fast-forward simulated time (delivers pending client events) and/or release stream jobs."""
    with store.lock:
        store.s["time_skew"] = store.s.get("time_skew", 0) + seconds
        store.s["released_extra"] += release
        store.materialize(acc); store.save()
    return {"ok": True, "events": acc["cursor"]}


class ScoreIn(BaseModel):
    job_id: str
    cover_letter: str
    bid_amount: float
    screening_answers: list[str] = []


@app.post("/eval/score")
def eval_score(body: ScoreIn, acc: dict = Depends(account)):
    """Stateless outcome for a proposal on a fixed job. Used by evals/runners/gigsim_outcomes.py."""
    job = _job(body.job_id)
    return score_proposal(job, store.hidden.get(job["job_id"], {}), store.clients.get(job["client_id"], {}), body.cover_letter, body.bid_amount, body.screening_answers, store.lexicon)


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail, "status": exc.status_code}, status_code=exc.status_code, headers=exc.headers or {})
