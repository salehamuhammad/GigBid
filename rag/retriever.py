"""Retriever factory. A variant is a *configuration* of one pipeline, so any variant can be
rerun, ablated one component at a time, or deployed by changing `rag.deployed_variant` (R6).

    get_retriever(owner)                 -> the deployed variant
    get_retriever(owner, "v2_hybrid")    -> a named variant from rag/variants/
    get_retriever(owner, VariantConfig(...))  -> an ad-hoc composition (ablation)
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import asdict, dataclass, replace
from functools import lru_cache

from agent.settings import get_settings
from rag.embeddings import get_embedder
from rag.index.bm25 import BM25
from rag.index.graph import SkillGraph
from rag.index.vector import get_store
from rag.ingest import pipeline
from rag.rerank import get_reranker
from rag.schema import Hit, RetrievalResult
from rag.skills import expand_aliases, extract_skills

EVIDENCE_TYPES = ("case_study", "repo", "review", "upload")


@dataclass(frozen=True)
class VariantConfig:
    name: str
    index: str = "plain"          # plain | multivector | contextual
    query: str = "whole"          # whole | decompose | hyde
    retrieval: str = "dense"      # dense | hybrid | graph
    rerank: bool = False
    outcome_boost: bool = False
    corrective: bool = False
    description: str = ""
    use_bm25: bool = True


@lru_cache
def variants() -> dict[str, VariantConfig]:
    import rag.variants as pkg
    out = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"rag.variants.{m.name}")
        if hasattr(mod, "CONFIG"): out[m.name] = mod.CONFIG
    best = get_settings().get("rag", "best")
    out["best"] = VariantConfig(name="best", description="Shipped composition (agent/config.yaml rag.best)", **best)
    return dict(sorted(out.items()))


class OwnerIndex:
    """Everything needed to search one owner's portfolio. Reloaded when the index is rebuilt."""
    def __init__(self, owner: str):
        pipeline.ensure_index(owner)
        self.owner = owner
        self.docs = {d.id: d for d in pipeline.load_docs(owner)}
        self.chunks = {k: pipeline.load_chunks(owner, k) for k in pipeline.KINDS}
        self._bm25: dict[str, BM25] = {}
        self._graph: SkillGraph | None = None

    def bm25(self, kind: str) -> BM25:
        if kind not in self._bm25: self._bm25[kind] = BM25([c.text for c in self.chunks[kind]])
        return self._bm25[kind]

    @property
    def graph(self) -> SkillGraph:
        if self._graph is None: self._graph = SkillGraph(list(self.docs.values()))
        return self._graph


_indexes: dict[str, tuple[float, OwnerIndex]] = {}


def owner_index(owner: str) -> OwnerIndex:
    pipeline.ensure_index(owner)
    mt = (get_settings().processed / "index" / owner / "manifest.json").stat().st_mtime
    if owner not in _indexes or _indexes[owner][0] != mt:
        _indexes[owner] = (mt, OwnerIndex(owner))
    return _indexes[owner][1]


_LEAD = re.compile(r"^(?:(?:must have|we need|please show|you will be responsible for|looking for)\b[^:]*?(?:\bwith|\bin|\busing|like this:|\bfor|:)|experience (?:with|in))\s+", re.I)
_TAIL = re.compile(r"\s+is (?:required|essential|a must)\.?$", re.I)


def heuristic_requirements(text: str) -> list[str]:
    """Split a job post into requirement-sized queries without an LLM: bullets first, then sentences."""
    bullets = [_TAIL.sub("", _LEAD.sub("", b.strip(" -*•\t"))).strip().rstrip(".") for b in re.findall(r"^\s*[-*•]\s+.+$", text or "", re.M)]
    if len(bullets) >= 2: return bullets[:8]
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text or "") if len(x.split()) >= 4]
    with_skill = [x for x in sents if extract_skills(x)]
    return (with_skill or sents)[:6]


def heuristic_hyde(text: str) -> str:
    skills = extract_skills(text)
    first = (text or "").strip().split("\n")[0][:160]
    return (f"I recently delivered a very similar project. {first} I built it with {', '.join(skills) or 'the tools you list'}, "
            f"shipped it to production and measured the result for the client.")


def rrf(rankings: list[list[str]], k: int = 60, weights: list[float] | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for w, ranking in zip(weights or [1.0] * len(rankings), rankings):
        for r, key in enumerate(ranking):
            out[key] = out.get(key, 0.0) + w / (k + r + 1)
    return out


class Retriever:
    def __init__(self, owner: str, cfg: VariantConfig, profile: str | None = None, *, reranker=None):
        self.owner, self.cfg, self.s = owner, cfg, get_settings()
        self.ix = owner_index(owner)
        self.emb = get_embedder(profile)
        self.rr = (reranker or get_reranker(profile)) if cfg.rerank or cfg.corrective else None
        self.k_rrf = self.s.get("rag", "rrf_k", default=60)
        self.pool = self.s.get("rag", "rerank_pool", default=30)

    # ---- stage 1: one query -> ranked documents
    def _chunk_ranking(self, query: str, n: int) -> list[tuple[int, float]]:
        kind = self.cfg.index
        qv = self.emb.embed([query])[0]
        dense = get_store().search(self.owner, kind, qv, n)
        if self.cfg.retrieval == "dense" or not self.cfg.use_bm25:
            return dense
        sparse = self.ix.bm25(kind).search(query, n)
        fused = rrf([[i for i, _ in dense], [i for i, _ in sparse]], self.k_rrf)
        return sorted(fused.items(), key=lambda x: -x[1])[:n]

    def _docs_for(self, query: str, types: tuple[str, ...]) -> list[Hit]:
        chunks = self.ix.chunks[self.cfg.index]
        per_doc: dict[str, Hit] = {}
        for idx, sc in self._chunk_ranking(query, self.pool * 4):
            c = chunks[idx]
            if c.meta.get("type") not in types: continue
            h = per_doc.get(c.doc_id)
            if h is None:
                per_doc[c.doc_id] = Hit(c.doc_id, sc, c.text[:400], {c.facet: sc})
            elif c.facet not in h.facets:
                h.facets[c.facet] = sc
                if self.cfg.index == "multivector": h.score += 0.5 * sc      # a second facet agreeing is extra evidence
        hits = sorted(per_doc.values(), key=lambda h: -h.score)
        if self.cfg.retrieval == "graph":
            g = [(d, sc) for d, sc in self.ix.graph.query(query, self.pool * 2) if self.ix.docs[d].type in types]
            fused = rrf([[h.doc_id for h in hits], [d for d, _ in g]], self.k_rrf, [1.0, 1.5])
            by_id = {h.doc_id: h for h in hits}
            for d, _ in g:
                by_id.setdefault(d, Hit(d, 0.0, self.ix.docs[d].text[:400], {"graph": 1.0}, why="skill graph"))
            for d, sc in fused.items(): by_id[d].score = sc
            hits = sorted(by_id.values(), key=lambda h: -h.score)
        hits = hits[: self.pool]
        if self.cfg.rerank and hits:
            scores = self.rr.score(query, [self._rerank_text(h) for h in hits], self.ix.bm25(self.cfg.index).idf)
            for h, sc in zip(hits, scores): h.score = float(sc)
            hits.sort(key=lambda h: -h.score)
        return hits

    def _rerank_text(self, h: Hit) -> str:
        d = self.ix.docs[h.doc_id]
        return f"{d.title}. {h.snippet}" + (f"\n{d.code[:600]}" if d.code and self.cfg.index == "multivector" else "")

    # ---- stage 2: queries -> merged result
    def _queries(self, job_text: str, requirements: list[str] | None, hyde_text: str | None) -> list[str]:
        if self.cfg.query == "decompose":
            # the whole post stays in as one ranking; each requirement adds its own (alias-expanded)
            reqs = [expand_aliases(r) for r in (requirements or heuristic_requirements(job_text))]
            return list(dict.fromkeys([job_text, *reqs]))
        if self.cfg.query == "hyde":
            return [hyde_text or heuristic_hyde(job_text)]
        return [job_text]

    def base_retrieve(self, job_text: str, requirements: list[str] | None = None, k: int = 10, types: tuple[str, ...] = EVIDENCE_TYPES,
                      hyde_text: str | None = None) -> RetrievalResult:
        queries = self._queries(job_text, requirements, hyde_text)
        per_q = {q: self._docs_for(q, types) for q in queries}
        if len(queries) == 1:
            hits = list(per_q[queries[0]])
        else:
            # whole-post ranking counts double; each requirement contributes only its confident head
            lists = [[h.doc_id for h in (hs if i == 0 else hs[:8])] for i, hs in enumerate(per_q.values())]
            fused = rrf(lists, self.k_rrf, [2.0] + [1.0] * (len(lists) - 1))
            best: dict[str, Hit] = {}
            for hs in per_q.values():
                for h in hs:
                    if h.doc_id not in best or h.score > best[h.doc_id].score: best[h.doc_id] = h
            hits = [replace(best[d], score=sc) for d, sc in sorted(fused.items(), key=lambda x: -x[1])]
        phrasing: list[Hit] = []
        if self.cfg.outcome_boost:
            w = self.s.get("rag", "outcome_weights")
            wins = self.ix.graph.project_wins
            for h in hits:
                proj = self.ix.docs[h.doc_id].meta.get("project", "")
                h.score *= 1 + 0.08 * min(wins.get(proj, 0.0), 3.0)      # evidence that has already won work
            hits.sort(key=lambda h: -h.score)
            props = self._docs_for(job_text, ("proposal",))
            for h in props: h.score *= w.get(self.ix.docs[h.doc_id].meta.get("outcome", ""), 1.0)
            phrasing = [h for h in sorted(props, key=lambda h: -h.score) if self.ix.docs[h.doc_id].meta.get("outcome") in ("won", "replied")][:3]
        return RetrievalResult(hits=hits[:k], per_requirement={q: hs[:3] for q, hs in per_q.items()}, phrasing=phrasing,
                               debug={"variant": self.cfg.name, "queries": queries, "config": asdict(self.cfg)})

    def grade(self, job_text: str, result: RetrievalResult) -> float:
        """Evidence strength in [0, 1]: the best reranker score among the top 3 hits."""
        if not result.hits: return 0.0
        rr = self.rr or get_reranker()
        sc = rr.score(job_text, [self._rerank_text(h) for h in result.hits[:3]], self.ix.bm25(self.cfg.index).idf)
        return float(max(sc))

    def retrieve(self, job_text: str, requirements: list[str] | None = None, k: int | None = None, types: tuple[str, ...] = EVIDENCE_TYPES,
                 hyde_text: str | None = None) -> RetrievalResult:
        k = k or self.s.get("rag", "top_k", default=10)
        if self.cfg.corrective:
            from rag.variants.v8_corrective import run_corrective
            return run_corrective(self, job_text, requirements, k, types, hyde_text)
        return self.base_retrieve(job_text, requirements, k, types, hyde_text)

    def item(self, hit: Hit) -> dict:
        d = self.ix.docs[hit.doc_id]
        return {"id": d.id, "type": d.type, "title": d.title, "source": d.meta.get("source", d.type), "date": d.meta.get("date", ""),
                "outcome": d.meta.get("outcome", ""), "project": d.meta.get("project", ""), "skills": d.meta.get("skills") or [],
                "snippet": re.sub(r"\s+", " ", hit.snippet)[:320], "score": round(float(hit.score), 4)}


def get_retriever(owner: str, variant: str | VariantConfig | None = None, profile: str | None = None, *, reranker=None) -> Retriever:
    if isinstance(variant, VariantConfig): cfg = variant
    else: cfg = variants()[variant or get_settings().get("rag", "deployed_variant", default="best")]
    return Retriever(owner, cfg, profile, reranker=reranker)
