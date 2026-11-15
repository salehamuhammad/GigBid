"""R&D question A: does tool granularity change agent behaviour?

40 tasks with known correct calls (evals/datasets/tool_tasks.json, generated below from the dev
set). Three tool surfaces are offered to the same model on its first turn:
  fine    -- one tool per marketplace/portfolio operation, terse auto-generated descriptions
  coarse  -- three tools (`marketplace`, `portfolio`, `workspace`) taking an `action` argument
  best    -- the shipped tools with the rewritten descriptions in the servers
Metrics: tool-selection accuracy (first relevant call names the expected tool), argument accuracy
(the expected key arguments match), tokens per task. REQUIRES a real model profile:
    MODEL_PROFILE=open GROQ_API_KEY=... python -m evals.runners.tool_granularity
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time

from evals.runners.common import PERSONAS, ROOT, dev, mean, mount_gigsim, save

TASKS = ROOT / "evals" / "datasets" / "tool_tasks.json"


def make_tasks(n=40, seed=9) -> list[dict]:
    rng, out = random.Random(seed), []
    rows = [(p, r) for p in PERSONAS for r in dev(p) if r["gold"]["kind"] == "normal"]
    for p, r in rng.sample(rows, n):
        j, k = r["job"], rng.randrange(5)
        if k == 0: out.append({"persona": p, "ask": f"Show me the full post for job {j['job_id']}.", "tool": "get_job", "args": {"job_id": j["job_id"]}})
        elif k == 1: out.append({"persona": p, "ask": f"Is client {j['client_id']} trustworthy? Check their history.", "tool": "get_client_history", "args": {"client_id": j["client_id"]}})
        elif k == 2: out.append({"persona": p, "ask": f"What do {j['category'].replace('_', ' ')} jobs usually pay?", "tool": "get_market_stats", "args": {"category": j["category"]}})
        elif k == 3:
            s = r["gold"]["required_skills"][0]
            out.append({"persona": p, "ask": f"Do I have portfolio proof of {s}?", "tool": "search_evidence", "args_contains": {"requirement": s}})
        else: out.append({"persona": p, "ask": "How many Connects do I have left?", "tool": "get_connects_balance", "args": {}})
    return out


async def run(surface: str, tasks: list[dict]) -> dict:
    from agent.llm import get_llm
    from agent.mcp_client import ToolBox
    llm = get_llm()
    if llm.offline: raise SystemExit("Needs a real model: set MODEL_PROFILE=open and GROQ_API_KEY.")
    tb = ToolBox("rq-a", tasks[0]["persona"])
    schemas = [t for t in await tb.list_tools() if t["annotations"].get("readOnlyHint")]
    names = {t["name"] for t in schemas}
    if missing := {t["tool"] for t in tasks} - names:
        raise RuntimeError(f"Missing required read tools: {sorted(missing)}")
    tools = []
    if surface == "coarse":
        for server in sorted({t["server"] for t in schemas}):
            group = [t for t in schemas if t["server"] == server]
            fields = {t["name"]: list(t["inputSchema"].get("properties", {})) for t in group}
            properties = {
                "action": {"type": "string", "description": "The exact operation name"},
                "arguments_json": {"type": "string", "description": "A JSON object encoded as a string. Use {} when no arguments are needed."},
            }
            tools.append({"type": "function", "function": {"name": server,
                          "description": f"Select one operation and provide its arguments. Operation fields: {json.dumps(fields)}",
                          "parameters": {"type": "object", "properties": properties,
                                         "required": ["action", "arguments_json"]}}})
    else:
        for t in schemas:
            description = t["name"].replace("_", " ") if surface == "fine" else t["description"]
            tools.append({"type": "function", "function": {"name": t["name"],
                          "description": description, "parameters": t["inputSchema"]}})
    model = llm.chat_model("writer").bind_tools(tools)
    res = []
    for task_id, t in enumerate(tasks, 1):
        t0 = time.perf_counter()
        error = None
        try:
            reply = await model.ainvoke([("user", t["ask"])])
            calls = reply.tool_calls
            usage = reply.usage_metadata or {}
            actual_model = reply.response_metadata.get("model_name")
        except Exception as exc:
            calls, usage, actual_model = [], {}, None
            error = {"type": type(exc).__name__, "http_status": getattr(exc, "status_code", None),
                     "provider_code": getattr(exc, "code", None)}
        first = calls[0] if calls else {"name": None, "args": {}}
        name, args = first["name"], first["args"]
        if surface == "coarse" and name:
            action = args.get("action")
            name = action if any(t["server"] == name and t["name"] == action for t in schemas) else None
            try:
                decoded = json.loads(args.get("arguments_json", ""))
            except (TypeError, ValueError):
                decoded = None
            args = decoded if isinstance(decoded, dict) else {}
            if not isinstance(decoded, dict):
                error = {"type": "InvalidCoarseArguments"}
        ok_tool = name == t["tool"]
        ok_args = ok_tool and error is None and (all(args.get(k) == v for k, v in t.get("args", {}).items()) and all(v.lower() in str(args.get(k, "")).lower() for k, v in t.get("args_contains", {}).items()))
        res.append({"task_id": task_id, "ask": t["ask"], "expected": t, "called": name,
                    "arguments": args, "tool_ok": ok_tool, "args_ok": ok_args, "usage": usage,
                    "model": actual_model, "requested_model": llm.model_for("writer"),
                    "latency_s": round(time.perf_counter() - t0, 3), "error": error,
                    "estimated_cost_usd": llm.cost(actual_model or llm.model_for("writer"), usage["input_tokens"], usage["output_tokens"]) if usage else None})
    measured = [r["usage"]["total_tokens"] for r in res if "total_tokens" in r["usage"]]
    return {"n": len(res), "errors": sum(r["error"] is not None for r in res),
            "tool_selection_accuracy": mean(r["tool_ok"] for r in res),
            "argument_accuracy": mean(r["args_ok"] for r in res),
            "tokens_per_task": mean(measured) if measured else None, "token_samples": len(measured), "rows": res}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=40); ap.add_argument("--output", default="tool_granularity"); a = ap.parse_args()
    if not 1 <= a.n <= 40: ap.error("--n must be between 1 and 40")
    if not TASKS.exists(): TASKS.write_text(json.dumps(make_tasks(), indent=1))
    tasks = json.loads(TASKS.read_text())[: a.n]
    mount_gigsim()
    out = {s: asyncio.run(run(s, tasks)) for s in ("fine", "coarse", "best")}
    print({s: {k: v for k, v in r.items() if k != "rows"} for s, r in out.items()})
    save(a.output, out)


if __name__ == "__main__":
    main()
