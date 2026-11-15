"""The product flow through the HTTP API: register -> onboard -> scout -> inbox -> approve ->
submitted -> client reply -> approve message. Also tenant isolation and auth."""
import asyncio

import httpx
import pytest

from worker import tasks
from worker.engine import ENGINE
from worker.queue import drain


@pytest.fixture
async def client():
    import os
    os.environ["GIGBID_NO_SCHEDULER"] = "1"
    from apps.api.main import app
    await ENGINE.start()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as c:
        yield c
    await drain(); await ENGINE.stop()


async def signup(c, email):
    r = await c.post("/api/auth/register", json={"email": email, "password": "correct-horse-1", "name": "T"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["id"]


async def test_scout_reports_missing_saved_searches(client):
    headers, _ = await signup(client, "no-search-e2e@example.com")
    response = await client.post("/api/jobs/scout", headers=headers)
    assert response.status_code == 200
    assert "Enable or add a saved search" in response.json()["detail"]


async def test_full_flow_and_tenancy(client):
    import uuid
    h, uid = await signup(client, f"a-{uuid.uuid4().hex[:6]}@example.com")
    assert (await client.get("/api/jobs")).status_code == 401
    personas = (await client.get("/api/personas")).json()
    assert {p["id"] for p in personas} == {"ai_engineer", "fullstack_dev", "data_analyst"}
    s = {"floor_rate": 35, "target_rate": 55, "min_project": 300, "connects_budget_week": 80, "autonomy": "suggest", "strategy": "evidence_first", "categories": [], "min_budget": 0, "marketplace": "gigsim", "onboarded": True}
    r = await client.post("/api/profile/onboard", json={"persona": "ai_engineer", "settings": s}, headers=h)
    assert r.status_code == 200 and r.json()["settings"]["onboarded"]
    await drain(); await tasks.scout_user(uid, True, 30); await drain()
    jobs = (await client.get("/api/jobs?sort=fit", headers=h)).json()
    assert len(jobs) >= 20 and {j["status"] for j in jobs} & {"awaiting_approval", "skipped"}
    assert any("scam" in " ".join(j["reasons"]).lower() or j["risk"] and j["risk"] >= 0.6 for j in jobs if j["status"] == "skipped")
    waiting = [j for j in jobs if j["status"] == "awaiting_approval"]
    assert waiting
    d = (await client.get(f"/api/jobs/{waiting[0]['job_id']}", headers=h)).json()
    assert d["approval_id"] and d["analysis"]["fit"]["matrix"] and d["proposal"]["draft"]["cover_letter"]

    # a second user sees none of this
    h2, _ = await signup(client, f"b-{uuid.uuid4().hex[:6]}@example.com")
    assert (await client.get("/api/jobs", headers=h2)).json() == []
    assert (await client.get(f"/api/approvals/{d['approval_id']}", headers=h2)).status_code == 404
    assert (await client.post(f"/api/approvals/{d['approval_id']}/decision", json={"action": "approve"}, headers=h2)).status_code == 404

    ap = (await client.get(f"/api/approvals/{d['approval_id']}", headers=h)).json()
    assert ap["payload"]["preview"]["dry_run"] and ap["payload"]["price"]["connects_cost"] > 0
    assert (await client.post(f"/api/approvals/{d['approval_id']}/decision", json={"action": "reject"}, headers=h)).status_code == 422
    r = await client.post(f"/api/approvals/{d['approval_id']}/decision", json={"action": "approve"}, headers=h)
    assert r.status_code == 200
    await drain()
    assert (await client.post(f"/api/approvals/{d['approval_id']}/decision", json={"action": "approve"}, headers=h)).status_code == 409      # double click
    board = (await client.get("/api/proposals", headers=h)).json()
    assert [p for p in board if p["job_id"] == d["job_id"]][0]["stage"] == "submitted"
    runs = (await client.get(f"/api/runs?ref={d['job_id']}", headers=h)).json()
    detail = (await client.get(f"/api/runs/{runs[-1]['id']}", headers=h)).json()
    assert {"analyst", "risk", "matcher", "writer", "critic"} <= {n["node"] for n in detail["nodes"]}
    assert detail["trace_id"] and any(e["type"] == "interrupt" for e in detail["events"])
    audit = (await client.get("/api/system/audit", headers=h)).json()
    assert any(a["tool"] == "submit_proposal" for a in audit) and all(a["user"] == uid for a in audit)
    a = (await client.get("/api/analytics", headers=h)).json()
    assert a["funnel"]["submitted"] == 1 and a["connects_spent"] > 0
    health = (await client.get("/api/system/health", headers=h)).json()
    assert health["status"] == "ok" and health["servers"]["marketplace"]


async def test_sse_replays_a_finished_run(client):
    import uuid
    h, uid = await signup(client, f"c-{uuid.uuid4().hex[:6]}@example.com")
    s = {"floor_rate": 35, "target_rate": 55, "min_project": 300, "connects_budget_week": 80, "autonomy": "suggest", "strategy": "evidence_first", "categories": ["llm_apps"], "min_budget": 0, "marketplace": "gigsim", "onboarded": True}
    await client.post("/api/profile/onboard", json={"persona": "ai_engineer", "settings": s}, headers=h)
    await drain(); await drain()
    run = (await client.get("/api/runs", headers=h)).json()[0]
    async with client.stream("GET", f"/api/runs/{run['id']}/stream", headers=h) as r:
        body = (await asyncio.wait_for(r.aread(), 10)).decode()
    assert "event: node_start" in body and "event: done" in body
