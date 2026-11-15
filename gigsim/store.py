"""GigSim state: seed data + per-account mutable state, persisted to one JSON file."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED = Path(os.getenv("GIGSIM_SEED_DIR", ROOT / "data" / "gigsim"))


class Store:
    def __init__(self, state_path: str | None = None):
        self.lock = threading.RLock()
        self.policy = yaml.safe_load((Path(__file__).parent / "policy.yaml").read_text())
        load = lambda n, d: json.loads((SEED / n).read_text()) if (SEED / n).exists() else d
        self.historical = load("jobs_historical.json", [])
        real = load("jobs_historical_real.json", [])       # written by scripts/prepare_kaggle.py
        self.historical += real
        self.stream = load("jobs_stream.json", [])
        self.dev = {j["job_id"]: j for j in load("jobs_dev.json", [])}
        self.clients = load("clients.json", {})
        self.hidden = load("hidden.json", {})
        self.msgs = load("client_messages.json", {})
        lex = ROOT / "data" / "skills_lexicon.json"
        self.lexicon = json.loads(lex.read_text()) if lex.exists() else {}
        self.jobs = {j["job_id"]: j for j in self.stream} | self.dev | {j["job_id"]: j for j in self.historical}
        self.path = Path(state_path or os.getenv("GIGSIM_STATE", ROOT / "gigsim" / "state" / "state.json"))
        self.interval = float(os.getenv("GIGSIM_STREAM_INTERVAL", "45"))
        self.delay = float(os.getenv("GIGSIM_EVENT_DELAY", "15"))
        self.s = {"start": time.time(), "released_extra": 0, "accounts": {}, "time_skew": 0.0}
        if self.path.exists():
            try: self.s = json.loads(self.path.read_text())
            except Exception: pass

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.s)); tmp.replace(self.path)

    def reset(self):
        self.s = {"start": time.time(), "released_extra": 0, "accounts": {}, "time_skew": 0.0}; self.save()

    def now(self) -> float: return time.time() + self.s.get("time_skew", 0.0)

    def released(self) -> list[dict]:
        n = 40 + int((self.now() - self.s["start"]) / max(self.interval, 1)) + self.s["released_extra"]
        return self.stream[: min(n, len(self.stream))]

    def account(self, name: str) -> dict:
        acc = self.s["accounts"].setdefault(name, {"connects": self.policy["connects"]["weekly_allowance"], "drafts": {}, "proposals": {},
                                                    "threads": {}, "events": [], "pending": [], "idem": {}, "calls": [], "cursor": 0})
        return acc

    def connects_cost(self, job: dict) -> dict:
        base = job.get("connects_cost", 8)
        sur = self.policy.get("update", {}).get("crowded_job_surcharge", {})
        extra = sur.get("extra_connects", 0) if job.get("proposals_so_far", 0) >= sur.get("proposals_threshold", 10**9) else 0
        return {"base": base, "surcharge": extra, "total": base + extra, "policy_version": self.policy["version"]}

    def emit(self, acc: dict, kind: str, at: float, **data):
        acc["pending"].append({"id": uuid.uuid4().hex[:12], "type": kind, "at": at, **data})

    def materialize(self, acc: dict):
        """Move due pending events into the visible event log (and create client messages)."""
        now = self.now()
        due = sorted([e for e in acc["pending"] if e["at"] <= now], key=lambda e: e["at"])
        acc["pending"] = [e for e in acc["pending"] if e["at"] > now]
        for e in due:
            if e["type"] == "client_message":
                th = acc["threads"].setdefault(e["thread_id"], {"thread_id": e["thread_id"], "job_id": e["job_id"], "client_id": e["client_id"], "messages": []})
                th["messages"].append({"id": e["id"], "from": "client", "text": e["text"], "at": e["at"], "intent_hint": None})
            if e["type"] in ("viewed", "replied", "interview", "hired", "lost") and e.get("proposal_id") in acc["proposals"]:
                acc["proposals"][e["proposal_id"]]["status"] = e["type"]
            acc["cursor"] += 1
            acc["events"].append({**e, "seq": acc["cursor"]})
