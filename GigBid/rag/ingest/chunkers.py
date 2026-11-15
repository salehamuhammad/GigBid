"""Chunkers for the three index kinds: plain (fixed chunks, V0), multivector (V5), contextual (V6)."""
from __future__ import annotations

import re

from rag.schema import Chunk, Doc


def _windows(text: str, words: int, overlap: int) -> list[str]:
    toks = text.split()
    if not toks: return []
    step = max(1, words - overlap)
    return [" ".join(toks[i:i + words]) for i in range(0, max(len(toks) - overlap, 1), step)]


def _meta(doc: Doc) -> dict:
    return {k: doc.meta.get(k, "") for k in ("persona", "type", "project", "skills", "date", "client_industry", "outcome")} | {"title": doc.title}


def plain(doc: Doc, words: int = 120, overlap: int = 20) -> list[Chunk]:
    """V0: fixed-size chunks; a repo is just its README followed by its code."""
    text = doc.text + ("\n\n" + doc.code if doc.code else "")
    return [Chunk(f"{doc.id}#p{i}", doc.id, w, "body", _meta(doc)) for i, w in enumerate(_windows(text, words, overlap))]


def code_symbols(code: str) -> list[str]:
    libs = re.findall(r"^\s*(?:from|import)\s+([\w.]+)", code, re.M) + re.findall(r"require\('([\w./@-]+)'\)", code) + re.findall(r"from '([\w./@-]+)'", code)
    return list(dict.fromkeys(l.split(".")[0] for l in libs))


def multivector(doc: Doc, words: int = 120, overlap: int = 20, summary: str | None = None) -> list[Chunk]:
    """V5: summary, README/body and code are indexed as separate vectors of one item."""
    m = _meta(doc)
    first = " ".join(re.sub(r"[#*`>-]", " ", doc.text).split()[:60])
    summ = summary or f"{doc.title}. {first}" + (f" Libraries used in the code: {', '.join(code_symbols(doc.code))}." if doc.code else "")
    out = [Chunk(f"{doc.id}#s", doc.id, summ, "summary", m)]
    out += [Chunk(f"{doc.id}#b{i}", doc.id, w, "readme" if doc.type == "repo" else "body", m) for i, w in enumerate(_windows(doc.text, words, overlap))]
    out += [Chunk(f"{doc.id}#c{i}", doc.id, w, "code", m) for i, w in enumerate(_windows(doc.code, words, overlap))]
    return out


def context_line(doc: Doc) -> str:
    """Deterministic context line (used when no LLM is configured). It deliberately uses only
    title / type / industry / date -- not the skills metadata -- so V6 is not handed the answer."""
    ind = doc.meta.get("client_industry") or "unspecified industry"
    return f"[From the {doc.type.replace('_', ' ')} \"{doc.title}\" ({ind} client, {doc.meta.get('date', 'n.d.')}; outcome: {doc.meta.get('outcome') or 'n/a'})]"


def contextual(doc: Doc, words: int = 120, overlap: int = 20, context: str | None = None) -> list[Chunk]:
    """V6: a context line is prepended to every chunk before embedding / BM25."""
    ctx = context or context_line(doc)
    return [Chunk(c.id.replace("#p", "#x"), c.doc_id, f"{ctx}\n{c.text}", c.facet, c.meta) for c in plain(doc, words, overlap)]
