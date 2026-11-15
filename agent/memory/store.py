"""Long-term memory on a LangGraph store (Postgres in production, SQLite locally).

Namespaces (all scoped by user id -- one tenant can never read another's memory):
  ("style", user)             promoted style rules            <- used by the Writer
  ("style_candidates", user)  observed-but-unpromoted patterns (not used by any agent)
  ("outcome", user)           promoted per-category hints     <- used by Pricing / Writer
  ("outcome_stats", user)     raw counts per category         (not used by any agent)
Writes go through agent/memory/promotion_rules.py only.
"""
from __future__ import annotations

import time

from langgraph.store.base import BaseStore

from agent.memory import promotion_rules as rules


class Memory:
    def __init__(self, store: BaseStore, user: str):
        self.store, self.user = store, user

    async def _all(self, kind: str) -> list[dict]:
        if self.store is None: return []
        return [{"kind": kind, "key": i.key, **i.value} for i in await self.store.asearch((kind, self.user), limit=200)]

    async def style_rules(self) -> list[dict]: return await self._all("style")
    async def outcome_hints(self) -> dict[str, dict]: return {i["category"]: i for i in await self._all("outcome")}

    async def snapshot(self) -> dict:
        return {"style": await self.style_rules(), "outcome": await self.outcome_hints()}

    async def record_edit(self, before: str, after: str, draft_id: str) -> dict:
        """A user edited a draft: update candidates, promote the ones that satisfy the rule."""
        patterns, promoted = rules.extract_edit_patterns(before, after), []
        for p in patterns:
            if rules.sanitize(p["description"]) is None: continue
            item = await self.store.aget(("style_candidates", self.user), p["key"])
            cand = item.value if item else {**p, "drafts": [], "first_seen": time.time()}
            if draft_id not in cand["drafts"]: cand["drafts"].append(draft_id)
            cand["last_seen"] = time.time()
            await self.store.aput(("style_candidates", self.user), p["key"], cand)
            if rules.should_promote_style(cand) and not await self.store.aget(("style", self.user), p["key"]):
                await self.store.aput(("style", self.user), p["key"], {**p, "evidence_drafts": cand["drafts"], "promoted_at": time.time(),
                                                                         "rule": f"seen in {len(cand['drafts'])} distinct edits"})
                promoted.append(p)
        return {"patterns": patterns, "promoted": promoted}

    async def record_outcome(self, obs: dict) -> dict | None:
        """A marketplace outcome arrived for one of our proposals: update counts, maybe promote a hint."""
        ns, key = ("outcome_stats", self.user), obs["category"]
        item = await self.store.aget(ns, key)
        stats = rules.update_outcome_stats(item.value if item else None, obs)
        await self.store.aput(ns, key, stats)
        if rules.should_promote_outcome(stats):
            hint = {**rules.outcome_hint(stats), "promoted_at": time.time(), "rule": f">= {stats['sent']} proposals with outcomes"}
            await self.store.aput(("outcome", self.user), key, hint)
            return hint
        return None

    async def list_all(self) -> list[dict]:
        out = []
        for kind in ("style", "outcome", "style_candidates", "outcome_stats"):
            out += await self._all(kind)
        return out

    async def delete(self, kind: str, key: str) -> None:
        """User deleted a memory item in Settings. A deleted style rule is marked reverted so it is not re-learned silently."""
        await self.store.adelete((kind, self.user), key)
        if kind == "style":
            item = await self.store.aget(("style_candidates", self.user), key)
            if item: await self.store.aput(("style_candidates", self.user), key, {**item.value, "reverted": True})
