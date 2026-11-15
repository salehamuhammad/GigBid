"""Embedders. Open models only (R: embeddings are open in every profile).

  fastembed -- ONNX on CPU (BAAI/bge-small-en-v1.5, nomic-embed-text-v1.5, ...)
  ollama    -- local Ollama /api/embed
  hash      -- deterministic hashed n-gram vectors; no download. Used by the `offline` profile
               and CI only. It is NOT a semantic embedding and is never the deployed choice.
Vectors are cached on disk by sha1(model + text), which is what makes re-indexing incremental.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from functools import lru_cache

import numpy as np

from agent.settings import get_settings


class Embedder:
    name = "base"
    def _embed(self, texts: list[str]) -> np.ndarray: raise NotImplementedError

    def __init__(self):
        path = get_settings().processed / "emb_cache.sqlite"
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._db.execute("create table if not exists e (k text primary key, v blob)")
        self._lock = threading.Lock()          # searches run in worker threads; sqlite connections are not re-entrant

    def embed(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            return self._embed_cached(texts)

    def _embed_cached(self, texts: list[str]) -> np.ndarray:
        keys = [hashlib.sha1((self.name + "\x00" + t).encode()).hexdigest() for t in texts]
        got = {}
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            for k, v in self._db.execute(f"select k, v from e where k in ({','.join('?' * len(part))})", part):
                got[k] = np.frombuffer(v, dtype=np.float32)
        missing = [i for i, k in enumerate(keys) if k not in got]
        if missing:
            vecs = self._embed([texts[i] for i in missing]).astype(np.float32)
            vecs /= (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
            for i, v in zip(missing, vecs):
                got[keys[i]] = v
            self._db.executemany("insert or replace into e values (?, ?)", [(keys[i], got[keys[i]].tobytes()) for i in missing]); self._db.commit()
        return np.vstack([got[k] for k in keys]) if keys else np.zeros((0, 1), dtype=np.float32)


class HashEmbedder(Embedder):
    def __init__(self, dim: int = 1024):
        from sklearn.feature_extraction.text import HashingVectorizer
        self.name = f"hash-{dim}"
        self._v = HashingVectorizer(n_features=dim, ngram_range=(1, 2), alternate_sign=False, norm=None, lowercase=True, token_pattern=r"[A-Za-z][A-Za-z0-9+#.]*")
        super().__init__()
    def _embed(self, texts): return np.log1p(self._v.transform(texts).toarray())


class FastEmbedder(Embedder):
    def __init__(self, model: str):
        from fastembed import TextEmbedding
        self.name = model; self._m = TextEmbedding(model_name=model)
        super().__init__()
    def _embed(self, texts): return np.array(list(self._m.embed(texts)))


class OllamaEmbedder(Embedder):
    def __init__(self, model: str):
        self.name = "ollama:" + model; self.model = model
        super().__init__()
    def _embed(self, texts):
        import httpx
        r = httpx.post(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/api/embed", json={"model": self.model, "input": texts}, timeout=120)
        r.raise_for_status(); return np.array(r.json()["embeddings"])


@lru_cache
def get_embedder(profile_name: str | None = None) -> Embedder:
    s = get_settings()
    cfg = s.cfg["models"]["profiles"][profile_name or s.profile_name]["embeddings"]
    provider = os.getenv("EMBEDDINGS_PROVIDER") or cfg["provider"]
    if provider == "fastembed": return FastEmbedder(cfg["model"])
    if provider == "ollama": return OllamaEmbedder(cfg["model"])
    return HashEmbedder()
