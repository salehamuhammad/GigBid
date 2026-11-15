# GigBid — R&D report (draft)

Skeleton in the required ten-section order. Numbers marked **[offline]** come from
`evals/results/*.json` under `MODEL_PROFILE=offline` (heuristic agents, hashed embeddings, lexical
reranker); replace them with the `open` profile run before submitting. Every claim should cite a
results file, trace or commit. Keep the PDF to 10 pages; tables can go in appendices.

## 1. Problem and constraints
* The freelancer's loop: find jobs, judge fit and risk, write a specific proposal, price it against
  Connects, answer clients. The expensive mistakes are bidding on scams, inventing experience,
  underpricing, and burning Connects on poor fits.
* **Never automated:** submitting a proposal, sending a message, spending Connects, leaving the
  platform. Enforced by `interrupt()` gates, write tools reachable only from the gate nodes, and
  idempotency keys (ADR 0004). There is no auto-send setting.
* Declared budgets (`agent/config.yaml budgets.declared`): p95 12 s per job analysed, 45 s per
  proposal; USD 0.002 per job analysed, USD 0.01 per proposal.

## 2. Architecture
Both graphs (`docs/graphs/*.mmd`, rendered from code), the marketplace port (ADR 0001), the 19 MCP
tools (`docs/TOOLS.md`), the stores (Postgres: checkpoints, long-term memory, app tables; Qdrant or
numpy: vectors; BM25 and the skill graph in memory). One paragraph per agent on why it exists
(README table). Three things kept apart in state (`agent/state.py` docstring): working state, the
execution trace, long-term memory (only via promotion rules, ADR 0005).

## 3. R&D question A — tool granularity
Hypothesis (write before running). Setup: 40 tasks in `evals/datasets/tool_tasks.json`, three
surfaces (fine / coarse / shipped descriptions), same ReAct agent. Results: `evals/results/tool_granularity.json`
(**run with `open`**). Conclusion.

## 4. R&D question B — RAG
**Hypothesis (stated before running):** "Requirement decomposition plus hybrid retrieval raises
evidence Recall@5 by 15 points over V0."

Results [offline] (`evals/results/rag.json`, mean over three personas):

| Variant | Recall@5 | nDCG@10 | Refusal acc. |
|---|---|---|---|
| V0 naive | 0.554 | 0.555 | 0 |
| V1 decompose | 0.553 | 0.564 | 0 |
| V2 hybrid | 0.634 | 0.632 | 0 |
| V3 rerank | 0.682 | 0.700 | 0 |
| V8 corrective | 0.697 | 0.696 | 0.62 |
| V9 skill graph | 0.776 | 0.791 | 0 |
| **shipped best** (graph + rerank + corrective) | 0.742 | 0.738 | 0.62 |

* Hypothesis: decomposition **alone** did nothing (V1 ≈ V0); hybrid added ~8 points. The 15-point
  lift needed reranking or the skill graph. Partly rejected.
* V9 leads but is partly circular (gold labels come from the same skill tags; see the data card).
* Ablation (`ablation.json`): removing the corrective loop *raises* ranking metrics (0.746 → 0.782
  nDCG) but drops refusal accuracy from 0.63 to 0 — the shipped choice trades ranking for not
  dressing up weak evidence as fit. Removing decomposition drops refusal to 0.23.
* Claim verification: unsupported-claim rate before/after **[offline: 0 → 0; the template writer
  cannot invent claims; rerun with `open`]**. The stub-model test shows a fabricated claim removed.
* Where better retrieval did not raise reply rate: compare `rag.json` with `gigsim_outcomes.json`
  per persona after the open run.

## 5. R&D question C — single agent vs supervisor vs graph
`evals/runners/baselines.py`, 50 dev jobs. **Run with `open`.** Report bid/skip accuracy,
unsupported claims, violations caught, P(reply), tokens, latency; say where (a) wins.

## 6. The change request
ADR 0006: policy file edit, no agent code changes; the dry-run preview shows the surcharge.
Measure: time from reading the change to green tests.

## 7. Signature extension (X2: A/B test of opening strategy)
Paired design on the same 74 jobs with common random numbers (`experiment_ab.json`):
question-first vs evidence-first **+0.001 P(reply), 95% CI [0.000, 0.003], sign test p = 1.0** —
a null result. Both beat a generic letter by +0.43 (CI [0.39, 0.47]), but that gap is partly by
construction (the simulated client rewards features GigBid was built for).

## 8. Failure analysis (≥ 10 jobs; taxonomy)
`evals/runners/failure_analysis.py` → `failures.json`. Offline the graph failed only 2 dev jobs
(missed evidence → wrong skip); the open run will add more. Failures found and fixed during
development (commits):

| Category | Case | Fix | Worked? |
|---|---|---|---|
| injection | `[[instruction]]` template reached the model in 20% of injected jobs (`\b` after `]]` never matches) | pattern rewritten | yes: exposure 0.20 → 0.00 |
| compliance miss (scam bid) | unpaid-trial and gift-card scams scored 0.4–0.5 < 0.6 limit; scam recall 0.71 | any policy-breaking flag is disqualifying | yes: 1.00 |
| missed evidence | decomposed queries drowned the whole-post ranking (V1 < V0) | keep the whole post as a double-weight query | partly |
| tool error | per-instance rate limiter let in-process runs exceed GigSim's 30/min | one shared limiter; overflow parks the job as `queued` | yes |
| tool error | corrective retriever kept a non-serialisable object in graph state | moved to runtime context | yes |

## 9. Safety and platform respect
Never: submit/send/spend without approval, move off-platform, scrape, claim unproven experience,
follow instructions in client text. Enforcement: gates + allowlists + idempotency; Compliance
rules as data (`rules.yaml`); injection quarantine before any model reads the text (0% exposure
[offline]); PII masking in logs and LangSmith; encrypted OAuth tokens; tenant-scoped queries
(tested). What still gets through: paraphrased injections the patterns don't match (Risk Assessor
model is the second line); claims that are true of the portfolio but misleadingly combined.

## 10. Hidden test results vs budgets
Fill from the instructor's hidden run. Offline measured: p95 0.30 s per job analysed, tokens ~4.9k
(estimated) per job, USD 0 (no model). Report the open-profile cost and latency against the declared
budgets, and the optimisation that helped (small models on analyst/risk/matcher, cached reference
lookups, early skip before pricing/writing).
