"""Exercise the production worker approval path against disposable PostgreSQL and GigSim."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


async def verify_phase(phase: str, fixture: Path):
    import httpx
    from sqlalchemy import select

    from agent.mcp_client import ToolBox
    from agent.settings import get_settings
    from apps.api.auth.security import DEFAULT_SETTINGS, create_user
    from apps.api.db import Approval, Job, Proposal, session
    from evals.runners.common import dev, mount_gigsim
    from worker import tasks
    from worker.engine import ENGINE

    settings = get_settings()
    assert settings.is_postgres and settings.marketplace_mode == "gigsim"
    assert settings.profile_name == "offline" and os.environ.get("GIGSIM_STATE")
    app = mount_gigsim()
    opts = {"floor_rate": 35, "target_rate": 55, "min_project": 300, "connects_budget_week": 80}
    if phase == "prepare":
        user = create_user("recovery-proof@example.test", os.urandom(24).hex(), "Recovery test",
                           owner="ai_engineer", settings={**DEFAULT_SETTINGS, **opts})
        row = next(row for row in dev("ai_engineer") if row["gold"]["kind"] == "normal"
                   and row["gold"]["bid"] and row["gold"]["fit"] == 1.0)
        job_id = row["job"]["job_id"]
        tools = ToolBox(user.id, "ai_engineer")
        payload = await tools.call("scout", "marketplace.get_job", {"job_id": job_id})
        with session() as db:
            db.add(Job(user_id=user.id, job_id=job_id, title=payload["title"],
                       category=payload["category"], payload=payload))
        await tasks.run_bid(user.id, job_id)
        with session() as db:
            approval = db.scalars(select(Approval).where(Approval.user_id == user.id)).one()
            assert approval.status == "pending"
            fixture.write_text(json.dumps({"user": user.id, "job": job_id, "approval": approval.id,
                                           "thread": approval.thread_id}), encoding="utf-8")
        balance = (await tools.call("pricing", "marketplace.get_connects_balance", {}))["balance"]
        assert balance == 120
    else:
        proof = json.loads(fixture.read_text(encoding="utf-8"))
        user_id, job_id, approval_id = (proof[key] for key in ("user", "job", "approval"))
        args = (user_id, approval_id, {"action": "approve"})
        if phase == "after-submit":
            call = ToolBox.call

            async def crash_after_submit(self, role, tool, payload, *args, **kwargs):
                result = await call(self, role, tool, payload, *args, **kwargs)
                if tool == "marketplace.submit_proposal":
                    os._exit(91)
                return result

            ToolBox.call = crash_after_submit
            await tasks.resume_bid(*args)
            raise AssertionError("Simulator submit crash point was not reached")
        if phase == "before-projection":
            await tasks.recover()
            eng = await tasks.engine()
            snap = await eng.bid.aget_state({"configurable": {"thread_id": proof["thread"]}})
            assert snap.next == ("submit",), snap.next

            async def crash_before_projection(*args):
                os._exit(92)

            tasks.sync_bid = crash_before_projection
            await tasks.resume_bid(*args)
            raise AssertionError("Projection crash point was not reached")
        await tasks.recover()
        eng = await tasks.engine()
        snap = await eng.bid.aget_state({"configurable": {"thread_id": proof["thread"]}})
        assert not snap.next and snap.values["status"] == "submitted"
        with session() as db:
            assert db.get(Approval, approval_id).status == "processing"
        assert await tasks.resume_bid(*args)
        assert await tasks.resume_bid(*args) is None
        headers = {"Authorization": f"Bearer {settings.gigsim_token}", "X-Account": user_id}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gigsim", headers=headers) as client:
            proposals = (await client.get("/proposals")).raise_for_status().json()["proposals"]
        assert len(proposals) == 1 and proposals[0]["job_id"] == job_id
        marketplace = proposals[0]
        tools = ToolBox(user_id, "ai_engineer")
        balance = (await tools.call("pricing", "marketplace.get_connects_balance", {}))["balance"]
        assert marketplace["connects_spent"] > 0 and balance == 120 - marketplace["connects_spent"]
        with session() as db:
            projected = db.scalars(select(Proposal).where(Proposal.user_id == user_id)).one()
            assert projected.stage == "submitted" and projected.marketplace_proposal_id == marketplace["proposal_id"]
            assert db.get(Approval, approval_id).status == "approved"
        print(json.dumps({"passed": True, "checkpoint": "PostgreSQL", "job_id": job_id,
                          "proposal_id": marketplace["proposal_id"], "marketplace_proposals": 1,
                          "connects_before": 120, "connects_after": balance, "duplicate_resume": "ignored",
                          "injected_worker_exits": [91, 92]}), flush=True)
    await ENGINE.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase")
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    if args.phase:
        asyncio.run(verify_phase(args.phase, args.fixture))
        return
    if os.environ.get("GIGBID_DISPOSABLE_POSTGRES") != "1":
        parser.error("Use a disposable PostgreSQL service and set GIGBID_DISPOSABLE_POSTGRES=1")
    with tempfile.TemporaryDirectory(prefix="gigbid-postgres-proof-") as directory:
        fixture = Path(directory) / "fixture.json"
        os.environ["GIGSIM_STATE"] = str(fixture.with_name("gigsim.json"))
        for phase, expected in (("prepare", 0), ("after-submit", 91), ("before-projection", 92), ("verify", 0)):
            result = subprocess.run([sys.executable, "-m", "scripts.verify_postgres_recovery",
                                     "--phase", phase, "--fixture", str(fixture)], timeout=240)
            if result.returncode != expected:
                raise SystemExit(f"{phase} exited {result.returncode}, expected {expected}")


if __name__ == "__main__":
    main()
