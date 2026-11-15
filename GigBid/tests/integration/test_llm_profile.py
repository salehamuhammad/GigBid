"""The real-model code path, exercised against a local OpenAI-compatible stub (no key, no network):
structured output parsing, per-node model routing, token/cost accounting, fallback on bad output,
and -- the point of the product -- a fabricated claim written by the 'model' is removed before
the human ever sees the draft."""
import json
import re
import socket
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, Request
from langgraph.store.memory import InMemoryStore

from agent.graphs.bid_graph import build_bid_graph
from agent.llm import LLM
from agent.mcp_client import ToolBox
from agent.runtime import Ctx
from agent.settings import get_settings
from tests.integration.test_bid_graph import USER, pick

stub = FastAPI()
seen_models: dict[str, str] = {}
FAKE = "I spent 15 years at Google leading a team of 40 engineers."


@stub.post("/v1/chat/completions")
async def chat(req: Request):
    body = await req.json()
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    role = re.search(r"You are (?:the |a |an )?(.+?)(?: in | for |\.|,)", system).group(1).strip().lower()
    seen_models[role] = body["model"]
    if role.startswith("job analyst"):
        out = {"job_id": "x", "title": "x", "summary": "s", "requirements": ["Docker", "object detection", "PyTorch"], "required_skills": ["Docker", "YOLO", "PyTorch"]}
    elif role.startswith("risk"):
        out = {"score": 0.05, "level": "low", "flags": [], "explanation": "normal job"}
    elif role.startswith("fit matcher"):
        reqs = [p["requirement"] for p in json.loads(user[user.index("["):])]
        out = {"matches": [{"requirement": r, "covered": True, "strength": 0.9} for r in reqs]}
    elif role.startswith("proposal writer"):
        eid = re.search(r"\[(ai_engineer-case-\d+)\]", user).group(1)
        out = {"sentences": [{"text": "Your weld inspection job matches a project I delivered for a manufacturing client.", "evidence_ids": [eid], "paragraph": 0},
                             {"text": FAKE, "evidence_ids": [eid], "paragraph": 0},
                             {"text": "Could you share sample footage so I can confirm the scope?", "evidence_ids": [], "paragraph": 1}], "screening_answers": []}
    elif role.startswith("strict fact checker"):
        out = "this is not json"                                  # forces the fallback model, then the heuristic
    elif role.startswith("critic"):
        out = {"verdict": "approve", "grounding": 0.9, "personalisation": 0.9, "length_ok": True, "reasons": [], "instructions": []}
    else:
        out = {"violations": []}
    content = out if isinstance(out, str) else json.dumps(out)
    return {"id": "c1", "object": "chat.completion", "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


@pytest.fixture(scope="module")
def stub_url():
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    server = uvicorn.Server(uvicorn.Config(stub, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if server.started: break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}/v1"
    server.should_exit = True


async def test_model_path_routes_accounts_and_strips_fabrication(stub_url, monkeypatch):
    profiles = get_settings().cfg["models"]["profiles"]
    monkeypatch.setitem(profiles, "stub", {**profiles["open"], "base_url": stub_url, "api_key": "test", "embeddings": profiles["offline"]["embeddings"], "reranker": profiles["offline"]["reranker"],
                                           "fallback_model": profiles["open"]["nodes"]["writer"],
                                           "price_per_mtok": {profiles["open"]["nodes"]["writer"]: [1.0, 2.0]}})
    monkeypatch.setitem(get_settings().cfg["budgets"], "max_revisions", 0)
    llm = LLM("stub")
    row, user = pick(), "u-llm"
    tools = ToolBox(user, "ai_engineer", "trace-llm")
    job = await tools.call("scout", "marketplace.get_job", {"job_id": row["job"]["job_id"]})
    graph, cfg = build_bid_graph(None, InMemoryStore()), {"configurable": {"thread_id": "t-llm"}}
    usage, final = [], {}
    async for mode, ev in graph.astream({"job": job, "user": USER}, cfg, context=Ctx(user_id=user, owner="ai_engineer", tools=tools, llm=llm), stream_mode=["updates"]):
        for name, upd in ev.items():
            if isinstance(upd, dict):
                usage += upd.get("usage", []); final.update({k: v for k, v in upd.items() if k in ("draft", "verification", "status")})
            elif name == "__interrupt__": final["payload"] = upd[0].value
    nodes = profiles["open"]["nodes"]
    assert seen_models["proposal writer"] == nodes["writer"] and seen_models["job analyst"] == nodes["analyst"]      # small and strong models routed per node
    w = next(u for u in usage if u["node"] == "writer")
    assert w["input_tokens"] == 100 and w["output_tokens"] == 20 and w["cost_usd"] == pytest.approx((100 * 1.0 + 20 * 2.0) / 1e6)
    v = next(u for u in usage if u["node"] == "verifier")
    assert v["model"] == "heuristic-fallback" and v["fallback"] and len(v["errors"]) == 2                           # model -> fallback model -> heuristic
    assert final["verification"]["unsupported_before"] >= 1 and final["verification"]["unsupported_after"] == 0
    assert FAKE in final["verification"]["removed"]
    assert "Google" not in final["payload"]["draft"]["cover_letter"]                                                # the invented claim never reaches the human
