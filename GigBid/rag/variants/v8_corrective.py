"""V8 (agentic, required one of V8/V9): corrective RAG as a LangGraph loop.

    retrieve -> grade --strong--> accept
                  |--weak, budget left--> rewrite -> retrieve
                  |--weak, no budget----> refuse   (the writer is told there is no evidence
                                                    and must not claim experience)
Targets jobs the persona should skip: weak evidence must not be dressed up as fit.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from agent.settings import get_settings
from rag.retriever import VariantConfig
from rag.schema import RetrievalResult
from rag.skills import expand_aliases, extract_skills

CONFIG = VariantConfig(name="v8_corrective", query="decompose", retrieval="hybrid", rerank=True, corrective=True, description="Corrective RAG loop")


@dataclass
class RCtx:
    retriever: Any          # kept out of the state: it is not data and must never be checkpointed


class CState(TypedDict, total=False):
    job_text: str
    requirements: list[str] | None
    k: int
    types: tuple
    hyde_text: str | None
    result: RetrievalResult
    grade: float
    floor: float
    attempts: int
    refused: bool


def _retrieve(s: CState, runtime: Runtime[RCtx]) -> dict:
    r = runtime.context.retriever.base_retrieve(s["job_text"], s.get("requirements"), s["k"], s["types"], s.get("hyde_text"))
    return {"result": r, "attempts": s.get("attempts", 0) + 1}


def _grade(s: CState, runtime: Runtime[RCtx]) -> dict:
    return {"grade": runtime.context.retriever.grade(s["job_text"], s["result"]), "floor": _floor(runtime.context.retriever)}


def _floor(retriever) -> float:
    c = get_settings().get("rag", "corrective")
    return c["min_score"]["lexical" if getattr(retriever.rr, "name", "") == "lexical-overlap" else "cross_encoder"]


def _route(s: CState) -> str:
    c = get_settings().get("rag", "corrective")
    if s["grade"] >= s["floor"]: return "accept"
    return "rewrite" if s["attempts"] <= c["max_requery"] else "refuse"


def _rewrite(s: CState) -> dict:
    """Re-query on canonical skill names + aliases only: drops the client's filler prose."""
    skills = extract_skills(s["job_text"])
    return {"requirements": skills or [expand_aliases(s["job_text"])]}


def _refuse(s: CState) -> dict:
    r = s["result"]
    return {"result": RetrievalResult(hits=[], per_requirement=r.per_requirement, refused=True, phrasing=[], debug={**r.debug, "grade": s["grade"], "attempts": s["attempts"]}), "refused": True}


def _accept(s: CState) -> dict:
    s["result"].debug.update({"grade": s["grade"], "attempts": s["attempts"]})
    return {"result": s["result"]}


@lru_cache
def corrective_graph():
    g = StateGraph(CState, context_schema=RCtx)
    for name, fn in (("retrieve", _retrieve), ("grade", _grade), ("rewrite", _rewrite), ("refuse", _refuse), ("accept", _accept)):
        g.add_node(name, fn)
    g.add_edge(START, "retrieve"); g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", _route, {"accept": "accept", "rewrite": "rewrite", "refuse": "refuse"})
    g.add_edge("rewrite", "retrieve"); g.add_edge("accept", END); g.add_edge("refuse", END)
    return g.compile(checkpointer=False)      # a pure function of its inputs; nothing to persist


def run_corrective(retriever, job_text, requirements, k, types, hyde_text) -> RetrievalResult:
    out = corrective_graph().invoke({"job_text": job_text, "requirements": requirements, "k": k, "types": types, "hyde_text": hyde_text, "attempts": 0},
                                    config={"configurable": {}, "callbacks": []}, context=RCtx(retriever))
    return out["result"]
