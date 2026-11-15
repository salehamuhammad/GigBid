"""Compile evals/results/*.json into the README's results section (between the RESULTS markers)."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"


def load(name):
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def retrieval_outcomes_table(study, *, vertical=False):
    fields = (
        ("Recall@5", "recall@5", ".4f"),
        ("nDCG@10", "ndcg@10", ".4f"),
        ("Unsupported claims/cover letter", "unsupported_per_proposal", ".2f"),
        ("AI rubric score /5", "judge_overall", ".2f"),
        ("Replies/scored draft", "reply_rate_per_scored_proposal", ".1%"),
        ("Replies/assigned job", "replies_per_assigned_job", ".1%"),
        ("Proposal p95 (s)", "p95_proposal_s", ".2f"),
        ("USD/proposal", "cost_per_proposal_usd", ".6f"),
    )
    rows = []
    shipped = study["env"]["deployed_variant"]
    for arm, stats in study["summary"].items():
        row = [arm + (" (configured at run time)" if arm == shipped else "")]
        row.extend(format(stats[key], fmt) if stats[key] is not None else "—" for _, key, fmt in fields)
        row.append(f"{stats['drafts']}/{stats['jobs']}")
        rows.append(row)
    headings = ["Variant", *(label for label, _, _ in fields), "Drafts/jobs"]
    if vertical:
        return table(["Metric", *(row[0] for row in rows)],
                     [[label, *(row[i] for row in rows)] for i, label in enumerate(headings[1:], 1)])
    return table(headings, rows)


def build() -> str:
    out = []
    rag = load("rag")
    if rag:
        env = rag["env"]
        out.append(f"**RAG variants** (all three personas, gold evidence from the dev set; profile `{env['model_profile']}`, embeddings `{env['embeddings']}`, reranker `{env['reranker']}`)\n")
        out.append(table(["Variant", "Recall@5", "MRR", "nDCG@10", "Refusal acc.", "p95 ms"],
                         [[k, v["recall@5"], v["mrr"], v["ndcg@10"], v["refusal_accuracy"], v["p95_ms"]] for k, v in sorted(rag["summary"].items(), key=lambda kv: -kv[1]["ndcg@10"])]))
    d = load("decision")
    if d:
        o = d["overall"]
        out.append("\n**Decisions and drafts** (whole bid graph)\n")
        out.append(table(["Persona", "Bid P", "Bid R", "Bid F1", "Scam recall", "Unsupported before", "Unsupported after", "p95 s", "USD/job"],
                         [[p, b["bid_precision"], b["bid_recall"], b["bid_f1"], b["scam_recall"], b["unsupported_claim_rate_before"], b["unsupported_claim_rate_after"], b["latency_p95_s"], b["usd_per_job"]]
                          for p, b in [("all", o), *d["by_persona"].items()]]))
    i = load("injection")
    if i:
        out.append("\n**Prompt injection** (planted canaries)\n")
        out.append(table(["Defences", "n", "Exposed to model", "Leaked into draft", "Detected", "Hijacked"],
                         [[k, v["n"], v["exposed"], v["leaked"], v["detected"], v["hijacked"]] for k, v in i["summary"].items()]))
    g = load("gigsim_outcomes")
    if g:
        out.append("\n**Simulated client outcomes** (paired, same jobs)\n")
        out.append(table(["Arm", "n", "Mean P(reply)", "Reply rate", "Hire rate"], [[k, v["n"], v["mean_p_reply"], v["reply_rate"], v["hire_rate"]] for k, v in g["arms"].items()]))
        for k in ("evidence_first_vs_generic", "question_first_vs_evidence_first"):
            c = g[k]; out.append(f"\n- {k.replace('_', ' ')}: diff {c['mean_diff_p_reply']:+.3f}, 95% CI {c['ci95']}, sign test p = {c['sign_test_p']} ({c['wins']} wins / {c['losses']} losses)")
    a = load("ablation")
    if a:
        out.append("\n\n**Ablations** (one component removed from the original composition)\n")
        out.append(table(["Configuration", "Recall@5", "MRR", "nDCG@10", "Refusal acc."],
                         [[k.replace("best (shipped)", "best (original)"), v["recall@5"], v["mrr"],
                           v["ndcg@10"], v["refusal_accuracy"]] for k, v in a["rag"].items()]))
        out.append("\n" + table(["Claim verification", "Drafts", "Claims", "Unsupported reaching the human", "Rate"],
                                [[k, v["drafts"], v["claims"], v["unsupported_reaching_human"], v["rate"]] for k, v in a["graph"].items()]))
    matched = load("retrieval_outcomes_open")
    if matched and matched.get("complete"):
        out.append("\n**Matched open-model retrieval and proposal outcomes** "
                   "([raw results](evals/results/retrieval_outcomes_open.json))\n")
        out.append(retrieval_outcomes_table(matched))
    return "\n".join(out) or "_No results yet. Run `make eval`._"


def main():
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    new = re.sub(r"<!-- RESULTS:START -->.*<!-- RESULTS:END -->", "<!-- RESULTS:START -->\n" + build() + "\n<!-- RESULTS:END -->", text, flags=re.S)
    readme.write_text(new, encoding="utf-8"); print("README results section updated")


if __name__ == "__main__":
    main()
