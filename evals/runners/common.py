"""Shared harness for every evaluation: one process, GigSim mounted in-process, MCP in-memory,
deterministic seeds. Results are written to evals/results/<name>.json with the config that
produced them (model profile, embedder, reranker, git-free timestamp)."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import statistics
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import NamedTemporaryFile

os.environ.setdefault("MCP_TRANSPORT", "inprocess")
os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGSIM_RATE_LIMIT", "100000")
os.environ.setdefault("MARKETPLACE_RPM", "100000")
os.environ.setdefault("GIGSIM_STATE", "/tmp/gigbid-eval-gigsim.json")

import httpx  # noqa: E402

from agent.settings import get_settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
PERSONAS = ("ai_engineer", "fullstack_dev", "data_analyst")


def mount_gigsim():
    from gigsim.app import app
    from mcp_servers.marketplace.adapters import gigsim
    gigsim.set_transport(httpx.ASGITransport(app=app))
    return app


def dev(persona: str) -> list[dict]:
    return json.loads((ROOT / "evals" / "datasets" / f"dev_{persona}.json").read_text())


def profile(persona: str) -> dict:
    return json.loads((get_settings().data_dir / "personas" / persona / "profile.json").read_text())


def sample(rows: list[dict], n: int | None, seed: int = 11) -> list[dict]:
    if not n or n >= len(rows): return rows
    rng = random.Random(seed)
    return rng.sample(rows, n)


def env_info() -> dict:
    s = get_settings()
    p = s.profile
    packages = {}
    for name in ("langgraph", "langgraph-supervisor", "fastembed", "qdrant-client"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            continue
    return {"model_profile": s.profile_name, "embeddings": os.getenv("EMBEDDINGS_PROVIDER") or p["embeddings"], "reranker": os.getenv("RERANKER_PROVIDER") or p["reranker"],
            "provider": p["provider"], "deployed_variant": s.get("rag", "deployed_variant"),
            "vector_store": "qdrant" if s.qdrant_url else "numpy", "at": datetime.now(timezone.utc).isoformat(),
            "dataset_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in sorted((ROOT / "evals" / "datasets").glob("*.json"))},
            "packages": packages}


def save(name: str, data: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{name}.json"
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=RESULTS, delete=False) as f:
        temp = Path(f.name)
        json.dump({"env": env_info(), **data}, f, indent=1, default=str)
    temp.replace(path)
    print(f"wrote {path}")
    return path


def mean(xs) -> float:
    xs = list(xs); return round(sum(xs) / len(xs), 4) if xs else 0.0


def pctl(xs, q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def bootstrap_ci(diffs: list[float], n: int = 2000, seed: int = 3) -> tuple[float, float]:
    rng = random.Random(seed)
    if not diffs: return (0.0, 0.0)
    ms = sorted(statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return round(ms[int(0.025 * n)], 4), round(ms[int(0.975 * n)], 4)


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact sign test."""
    n = wins + losses
    if n == 0: return 1.0
    k = min(wins, losses)
    return round(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n), 5)


def job_text(job: dict) -> str:
    return job["title"] + "\n" + job["description"]


async def run_to_gate(job_id: str, persona: str, user: dict | None = None, user_id: str | None = None, **ctx_flags) -> dict:
    """Run the bid graph for one job until the approval gate (or END). Returns final state + timing."""
    import uuid

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from agent.graphs.bid_graph import build_bid_graph
    from agent.mcp_client import ToolBox
    from agent.runtime import Ctx
    uid = user_id or "eval-" + uuid.uuid4().hex[:8]
    tools = ToolBox(uid, persona, "trace-eval")
    job = await tools.call("scout", "marketplace.get_job", {"job_id": job_id})
    graph, cfg = build_bid_graph(InMemorySaver(), InMemoryStore()), {"configurable": {"thread_id": f"eval:{uid}:{job_id}"}}
    t0 = time.perf_counter()
    prompts: list[str] = []
    async for _ in graph.astream({"job": job, "user": user or profile(persona)}, cfg, context=Ctx(user_id=uid, owner=persona, tools=tools, **ctx_flags), stream_mode=["updates"]):
        pass
    st = await graph.aget_state(cfg)
    v = dict(st.values)
    v["_latency_s"] = time.perf_counter() - t0
    v["_at_gate"] = bool(st.next)
    v["_prompts"] = prompts
    return v
