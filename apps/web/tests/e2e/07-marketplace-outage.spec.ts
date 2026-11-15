import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { onboard } from "./helpers";

const override = process.env.GIGBID_DISPOSABLE_COMPOSE_OVERRIDE;
const root = process.env.GIGBID_VERIFICATION_ROOT;

function compose(...args: string[]) {
  if (!override || !root) throw new Error("A disposable Compose override and the project root are required");
  return execFileSync("docker", [
    "compose", "-f", "infra/docker-compose.yml", "-f", override, "-p", "gigbid-final-verification", ...args,
  ], { cwd: root, encoding: "utf8", timeout: 40_000, windowsHide: true }).trim();
}

test("a real Marketplace MCP outage parks a bid run and recovers one proposal", async ({ page }) => {
  test.skip(!override || !root, "Requires the disposable GigBid verification stack");
  test.setTimeout(240_000);
  const email = await onboard(page);
  const token = await page.evaluate(() => localStorage.getItem("gigbid_token"));
  expect(token).toBeTruthy();
  const headers = { Authorization: `Bearer ${token}` };
  const setup = `
import asyncio, sys
from sqlalchemy import select, update
from agent.mcp_client import ToolBox
from apps.api.db import Job, SavedSearch, User, session
from evals.runners.common import dev

async def prepare():
    with session() as db:
        user = db.scalars(select(User).where(User.email == sys.argv[1])).one()
        user_id = user.id
        db.execute(update(SavedSearch).where(SavedSearch.user_id == user_id).values(enabled=0))
    row = next(r for r in dev("ai_engineer") if r["gold"]["kind"] == "normal"
               and r["gold"]["bid"] and r["gold"]["fit"] == 1.0)
    job_id = row["job"]["job_id"]
    data = await ToolBox(user_id, "ai_engineer").call("scout", "marketplace.get_job", {"job_id": job_id})
    with session() as db:
        db.add(Job(user_id=user_id, job_id=job_id, title=data["title"], category=data["category"], payload=data))
    print(job_id)

asyncio.run(prepare())
`;
  const jobId = compose("exec", "-T", "api", "python", "-c", setup, email).split(/\r?\n/).at(-1);
  expect(jobId).toMatch(/^dev-/);
  const jobUrl = `/api/jobs/${jobId}`;
  const readJob = async () => {
    const res = await page.request.get(jobUrl, { headers });
    expect(res.ok()).toBeTruthy();
    return res.json();
  };
  compose("stop", "mcp-marketplace");
  try {
    expect((await page.request.post(`${jobUrl}/analyze`, { headers })).ok()).toBeTruthy();
    await expect.poll(async () => (await readJob()).status, { timeout: 90_000 }).toBe("queued");
    await page.reload();
    await expect(page.getByRole("status").filter({ hasText: "Marketplace unavailable." }))
      .toContainText("1 job queued");
  } finally {
    compose("start", "mcp-marketplace");
  }
  await expect.poll(async () => (await readJob()).status, { timeout: 100_000 }).toBe("awaiting_approval");
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: "Marketplace unavailable." })).toHaveCount(0);
  const { approval_id: approvalId } = await readJob();
  const decisionUrl = `/api/approvals/${approvalId}/decision`;
  expect((await page.request.post(decisionUrl, { headers, data: { action: "approve" } })).ok()).toBeTruthy();
  await expect.poll(async () => (await readJob()).status).toBe("submitted");
  expect((await page.request.post(decisionUrl, { headers, data: { action: "approve" } })).status()).toBe(409);
  const readCount = `
import sys, httpx
from sqlalchemy import select
from agent.settings import get_settings
from apps.api.db import User, session
with session() as db:
    user_id = db.scalars(select(User.id).where(User.email == sys.argv[1])).one()
settings = get_settings()
headers = {"Authorization": "Bearer " + settings.gigsim_token, "X-Account": user_id}
proposals = httpx.get(settings.gigsim_url + "/proposals", headers=headers).raise_for_status().json()["proposals"]
print(sum(p["job_id"] == sys.argv[2] for p in proposals))
`;
  expect(compose("exec", "-T", "api", "python", "-c", readCount, email, jobId!)).toBe("1");
});
