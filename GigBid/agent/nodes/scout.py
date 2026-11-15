"""Scout: run saved searches, de-duplicate, queue new jobs (MCP: marketplace read).
Runs in the worker on a schedule (worker/tasks.py); `intake` is the first node of the bid graph,
where a scouted job is handed in and its untrusted text is scanned once for everything downstream."""
from __future__ import annotations

import hashlib
import re

from agent.guardrails import scan_untrusted
from agent.mcp_client import ToolBox
from agent.memory.store import Memory
from agent.runtime import Node, node


def signature(job: dict) -> str:
    """Content signature for duplicate detection: reposts keep the text and change the id."""
    text = re.sub(r"\W+", " ", (job.get("title", "") + " " + job.get("description", job.get("snippet", ""))).lower()).strip()
    return hashlib.sha1(text.encode()).hexdigest()[:16]


async def scout(tools: ToolBox, searches: list[dict], seen_ids: set[str], seen_signatures: dict[str, str], limit: int = 20, log: list | None = None, max_new: int = 5) -> list[dict]:
    """Returns new jobs (full posts). A job whose content matches one already seen is returned
    with `duplicate_of` set so the inbox can show it as a skipped duplicate instead of re-analysing it."""
    new: list[dict] = []
    for s in searches:
        res = await tools.call("scout", "marketplace.search_jobs", {"query": s.get("query", ""), "category": s.get("category"), "limit": limit}, log=log)
        for summary in res.get("jobs", []):
            jid = summary["job_id"]
            if jid in seen_ids or len(new) >= max_new: continue
            seen_ids.add(jid)
            job = await tools.call("scout", "marketplace.get_job", {"job_id": jid}, log=log)
            sig = signature(job)
            job["signature"] = sig
            if sig in seen_signatures: job["duplicate_of"] = seen_signatures[sig]
            else: seen_signatures[sig] = jid
            new.append(job)
    return new


@node("intake")
async def intake(n: Node) -> dict:
    job = dict(n.state["job"])
    scan = scan_untrusted(job.get("description", ""), defend=n.ctx.defences)
    job["description_raw"] = job.get("description", "")
    job["description"] = scan["cleaned"] if n.ctx.defences else job.get("description", "")
    job["injection"] = {"flagged": scan["flagged"], "matches": scan["matches"]}
    memory = await Memory(n.store, n.ctx.user_id).snapshot() if n.store is not None else {"style": [], "outcome": {}}
    n.emit(event="info", message=f"Job {job['job_id']} handed in" + (" - embedded instruction removed" if scan["flagged"] and n.ctx.defences else ""))
    return {"job": job, "memory": memory, "status": "analysing", "_summary": "injection text removed" if scan["flagged"] else "clean"}
