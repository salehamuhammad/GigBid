"""Rerankers (V3). Open cross-encoder via fastembed, or a lexical scorer for the offline profile."""
from __future__ import annotations

import math
import os
from functools import lru_cache
from threading import Lock

from agent.settings import get_settings
from rag.skills import expand_aliases, tokenize


class LexicalReranker:
    """IDF-weighted query-term coverage with alias expansion. Offline/CI stand-in only."""
    name = "lexical-overlap"
    def score(self, query: str, texts: list[str], idf: dict[str, float] | None = None) -> list[float]:
        # aliases are alternatives, not extra requirements: expand the *document* side, score the query as written
        q = set(tokenize(query))
        idf = idf or {}
        den = sum(idf.get(t, 1.0) for t in q) or 1.0
        out = []
        for t in texts:
            toks = set(tokenize(expand_aliases(t)))
            out.append(sum(idf.get(w, 1.0) for w in q & toks) / den)
        return out


class CrossEncoderReranker:
    def __init__(self, model: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.name = model; self._m = TextCrossEncoder(model_name=model)
    def score(self, query: str, texts: list[str], idf=None) -> list[float]:
        return [1 / (1 + math.exp(-float(x))) for x in self._m.rerank(query, texts)]


_MODEL_LOAD_LOCK = Lock()


@lru_cache
def _load_reranker(provider: str, model: str):
    return CrossEncoderReranker(model) if provider == "fastembed" else LexicalReranker()


def get_reranker(profile_name: str | None = None):
    s = get_settings()
    cfg = s.cfg["models"]["profiles"][profile_name or s.profile_name]["reranker"]
    provider = os.getenv("RERANKER_PROVIDER") or cfg["provider"]
    with _MODEL_LOAD_LOCK:
        return _load_reranker(provider, cfg["model"])
