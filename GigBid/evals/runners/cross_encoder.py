"""Resumable full-dev evaluation with the configured BGE cross-encoder."""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import OrderedDict

import numpy as np

from evals.runners.ablation import retrieval_ablations
from evals.runners.common import PERSONAS, RESULTS, dev, env_info, job_text, mean, pctl, save
from evals.runners.rag_eval import score
from rag.rerank import CrossEncoderReranker, get_reranker
from rag.retriever import get_retriever


class TinyBertReranker(CrossEncoderReranker):
    """Official ONNX export of the two-layer MS MARCO cross-encoder."""

    name = "cross-encoder/ms-marco-TinyBERT-L2-v2"

    def __init__(self):
        import onnxruntime as ort
        from huggingface_hub import HfApi, hf_hub_download
        from tokenizers import Tokenizer

        self.revision = HfApi().model_info(self.name).sha
        model = hf_hub_download(self.name, "onnx/model.onnx", revision=self.revision)
        tokenizer = hf_hub_download(self.name, "tokenizer.json", revision=self.revision)
        self.tokenizer = Tokenizer.from_file(tokenizer)
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(4, len(os.sched_getaffinity(0))) if hasattr(os, "sched_getaffinity") else 4
        self.session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
        self.inputs = {item.name for item in self.session.get_inputs()}

    def score(self, query, texts, idf=None):
        batch = self.tokenizer.encode_batch([(query, text) for text in texts])
        feeds = {
            "input_ids": np.asarray([item.ids for item in batch], dtype=np.int64),
            "attention_mask": np.asarray([item.attention_mask for item in batch], dtype=np.int64),
            "token_type_ids": np.asarray([item.type_ids for item in batch], dtype=np.int64),
        }
        logits = self.session.run(None, {key: feeds[key] for key in self.inputs})[0].reshape(-1)
        return (1 / (1 + np.exp(-np.clip(logits, -80, 80)))).tolist()


class ScoreCache:
    """Reuse scores for identical query and passage pairs in this synthetic evaluation."""

    def __init__(self, model: CrossEncoderReranker, capacity: int = 50_000):
        self.model = model
        self.name = model.name
        self.capacity = capacity
        self.cache: OrderedDict[tuple[str, str], float] = OrderedDict()

    def score(self, query, texts, idf=None):
        keys = [(query, text) for text in texts]
        missing = list(dict.fromkeys(key for key in keys if key not in self.cache))
        if missing:
            self.cache.update(zip(missing, self.model.score(query, [text for _, text in missing]), strict=True))
        values = []
        for key in keys:
            self.cache.move_to_end(key)
            values.append(self.cache[key])
        while len(self.cache) > self.capacity:
            self.cache.popitem(last=False)
        return values


def run(output, names, backend, with_ablations):
    environment = env_info()
    model = TinyBertReranker() if backend == "tinybert" else get_reranker()
    if not isinstance(model, CrossEncoderReranker) or environment["vector_store"] != "qdrant":
        raise SystemExit("Use the real cross-encoder and the existing BGE Qdrant indexes.")
    cached = ScoreCache(model)
    configs = {cfg.name: cfg for cfg in retrieval_ablations().values()} if with_ablations else {}
    names = list(dict.fromkeys([*names, *configs]))
    RESULTS.mkdir(parents=True, exist_ok=True)
    checkpoint = RESULTS / f"{output}.jsonl"
    signature = {k: environment[k] for k in ("dataset_sha256", "embeddings", "reranker", "vector_store")}
    if backend == "tinybert":
        signature["reranker"] = {"provider": "onnxruntime", "model": model.name, "revision": model.revision}
    signature["variants"] = list(names)
    if not checkpoint.exists():
        checkpoint.write_text(json.dumps(signature) + "\n", encoding="utf-8")
    with checkpoint.open(encoding="utf-8") as stream:
        if json.loads(next(stream)) != signature:
            raise RuntimeError("Checkpoint configuration differs. Choose a new output name.")
        rows = [json.loads(line) for line in stream]
    done = {(r["variant"], r["persona"], r["job_id"]) for r in rows}
    completed_this_run = 0
    with checkpoint.open("a", encoding="utf-8", buffering=1) as stream:
        for persona in PERSONAS:
            retrievers = {name: get_retriever(persona, configs.get(name, name), reranker=cached) for name in names}
            for row in dev(persona):
                gold, job = row["gold"], row["job"]
                if gold["kind"] == "duplicate":
                    continue
                for name, retriever in retrievers.items():
                    key = (name, persona, job["job_id"])
                    if key in done:
                        continue
                    started = time.perf_counter()
                    result = retriever.retrieve(job_text(job), k=10)
                    ids = [hit.doc_id for hit in result.hits]
                    record = {"variant": name, "persona": persona, "job_id": job["job_id"],
                              "category": gold["category"], "retrieved": ids, "gold": gold["evidence"],
                              "refused": result.refused or not ids,
                              "cached_eval_ms": round(1000 * (time.perf_counter() - started), 2)}
                    if gold["evidence"]:
                        record.update(score(ids, gold["evidence"]))
                    stream.write(json.dumps(record) + "\n")
                    rows.append(record)
                    done.add(key)
                    completed_this_run += 1
                    if completed_this_run % 10 == 0:
                        os.fsync(stream.fileno())
                        print(f"{name} {persona}: {len(rows)} scored records saved", flush=True)
    def summarize(subset):
        pos = [row for row in subset if row["gold"]]
        neg = [row for row in subset if not row["gold"]]
        return {
            "n": len(subset), "n_pos": len(pos), "n_neg": len(neg),
            **{metric: mean(row[metric] for row in pos) if pos else None for metric in ("recall@5", "mrr", "ndcg@10")},
            "refusal_accuracy": mean(row["refused"] for row in neg) if neg else None,
            "cached_eval_p95_ms": pctl([row["cached_eval_ms"] for row in subset], .95),
        }

    summary = {}
    for name in names:
        subset = [row for row in rows if row["variant"] == name]
        summary[name] = summarize(subset)
        for field in ("persona", "category"):
            summary[name][f"by_{field}"] = {
                group: summarize([row for row in subset if row[field] == group])
                for group in sorted({row[field] for row in subset})
            }
    save(output, {"env": {**environment, "reranker": signature["reranker"]},
                  "complete": True, "benchmark_configuration": signature,
                  "timing_note": "Evaluation with exact-pair score caching", "summary": summary, "rows": rows})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="rag_full_cross_encoder")
    parser.add_argument("--variants", nargs="+", default=["v3_rerank", "best"])
    parser.add_argument("--backend", choices=["configured", "tinybert"], default="configured")
    parser.add_argument("--with-ablations", action="store_true")
    args = parser.parse_args()
    run(args.output, args.variants, args.backend, args.with_ablations)
