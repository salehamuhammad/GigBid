"""Okapi BM25 over chunks (V2). Small, dependency-free, keeps tool names like `dbt` or `c#` intact."""
from __future__ import annotations

import math
from collections import Counter

from rag.skills import tokenize


class BM25:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [Counter(tokenize(t)) for t in texts]
        self.len = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.k1, self.b = k1, b
        self.postings: dict[str, list[int]] = {}
        for i, d in enumerate(self.docs):
            for t in d: self.postings.setdefault(t, []).append(i)

    def search(self, query: str, n: int = 30) -> list[tuple[int, float]]:
        scores: dict[int, float] = {}
        for t in set(tokenize(query)):
            for i in self.postings.get(t, []):
                f = self.docs[i][t]
                scores[i] = scores.get(i, 0.0) + self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
        return sorted(scores.items(), key=lambda x: -x[1])[:n]
