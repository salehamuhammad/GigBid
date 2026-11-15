"""Index building. `build_index(owner)` is incremental: embeddings are cached by content hash,
so adding one case study in the UI only embeds that document's chunks (B1)."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from agent.settings import get_settings
from rag.embeddings import get_embedder
from rag.index.vector import get_store
from rag.ingest import chunkers
from rag.ingest.loaders import load_corpus
from rag.schema import Chunk, Doc

KINDS = ("plain", "multivector", "contextual")


def _dir(owner: str) -> Path:
    d = get_settings().processed / "index" / owner; d.mkdir(parents=True, exist_ok=True); return d


def build_index(owner: str, kinds=KINDS, contexts: dict[str, str] | None = None) -> dict:
    s = get_settings(); t0 = time.time()
    gone = deleted_ids(owner)
    docs = [d for d in load_corpus(owner) if d.id not in gone]
    w, o = s.get("rag", "chunk_words"), s.get("rag", "chunk_overlap")
    emb = get_embedder(); stats = {"owner": owner, "docs": len(docs), "embedder": emb.name}
    (_dir(owner) / "docs.json").write_text(json.dumps([asdict(d) for d in docs]))
    for kind in kinds:
        chunks: list[Chunk] = []
        for d in docs:
            if kind == "plain": chunks += chunkers.plain(d, w, o)
            elif kind == "multivector": chunks += chunkers.multivector(d, w, o)
            else: chunks += chunkers.contextual(d, w, o, (contexts or {}).get(d.id))
        vecs = emb.embed([c.text for c in chunks])
        get_store().upsert(owner, kind, [c.id for c in chunks], vecs)
        (_dir(owner) / f"{kind}.chunks.json").write_text(json.dumps([asdict(c) for c in chunks]))
        stats[kind] = len(chunks)
    stats["seconds"] = round(time.time() - t0, 2)
    (_dir(owner) / "manifest.json").write_text(json.dumps(stats))
    return stats


def ensure_index(owner: str) -> None:
    if not (_dir(owner) / "manifest.json").exists():
        build_index(owner)


def load_docs(owner: str) -> list[Doc]:
    p = _dir(owner) / "docs.json"
    return [Doc(**d) for d in json.loads(p.read_text())] if p.exists() else []


def load_chunks(owner: str, kind: str) -> list[Chunk]:
    p = _dir(owner) / f"{kind}.chunks.json"
    return [Chunk(**c) for c in json.loads(p.read_text())] if p.exists() else []


def add_document(owner: str, filename: str, content: bytes, doc_type: str = "case_study", meta: dict | None = None) -> dict:
    """Save a user-uploaded portfolio file under the owner's tenant directory and re-index."""
    up = get_settings().processed / "uploads" / owner
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[:80]
    sub = {"case_study": "case_studies", "review": "reviews", "proposal": "proposals"}.get(doc_type, "uploads")
    if safe.lower().endswith(".pdf"):
        target = up / safe; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    else:
        target = up / sub / (Path(safe).stem + ".md"); target.parent.mkdir(parents=True, exist_ok=True)
        text = content.decode("utf-8", errors="ignore")
        if not text.startswith("---"):
            m = {"id": f"{owner}-up-{Path(safe).stem}", "type": doc_type, "persona": owner, "project": Path(safe).stem, "date": time.strftime("%Y-%m-%d"),
                 "client_industry": "", "outcome": "", "provenance": "user_upload", **(meta or {})}
            text = "---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in m.items()) + "\n---\n\n" + text
        target.write_text(text)
    return build_index(owner) | {"saved_as": str(target.name)}


def _tomb(owner: str) -> Path:
    d = get_settings().processed / "deleted"; d.mkdir(parents=True, exist_ok=True); return d / f"{owner}.json"


def deleted_ids(owner: str) -> set[str]:
    p = _tomb(owner)
    return set(json.loads(p.read_text())) if p.exists() else set()


def delete_document(owner: str, doc_id: str, restore: bool = False) -> bool:
    """Tombstone (or restore) one evidence item and re-index. Non-destructive: the file stays on
    disk. Viva Q3: delete the evidence, regenerate, and the claim that relied on it must go."""
    ids = deleted_ids(owner)
    (ids.discard if restore else ids.add)(doc_id)
    _tomb(owner).write_text(json.dumps(sorted(ids)))
    build_index(owner)
    return True
