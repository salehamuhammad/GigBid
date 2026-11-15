# GigBid assignment evidence

The assignment PDF defines the rubric. The student confirmed that the deadline was extended and that no November 2 policy update was issued. The [policy ADR](adr/0006-change-request.md) describes the simulator's synthetic example.

## A. MCP tool layer

- Docker reported all three MCP services healthy. The isolated Python test suite passed 28 tests across the original unit, MCP contract and integration suites and the trace-redaction test.
- The [final tool study](../evals/results/tool_granularity_open_final_40.json) records 120 attempts on GPT-OSS 120B. The three arms offered read-only schemas and measured the first turn. Terse fine-grained tools reached 85% selection and 77.5% argument accuracy. Shipped descriptions reached 92.5% and 82.5%. The improved coarse arm reached 70% and 67.5%. The [first](../evals/results/tool_granularity_open_40.json) and [second](../evals/results/tool_granularity_open_typed_40.json) coarse-schema trials are preserved as diagnostics. Provider usage is missing for rejected responses.
- The official MCP Inspector listed the [Portfolio](images/mcp-inspector-portfolio.png), [Marketplace](images/mcp-inspector-marketplace.png) and [Workspace](images/mcp-inspector-workspace.png) tools on isolated servers.
- Upwork's live metadata exposes authorization, token and registration endpoints. The local contract test verifies PKCE, one-time OAuth state, encrypted token storage and draft-only behavior. GigBid has zero connected Upwork accounts, so the account-authorized draft check is unavailable. The assignment conditions live operation on the student having an Upwork account.
- The [live GitHub MCP check](../evals/results/github_mcp_requests.json) used a cached local Git Credential Manager credential. GitHub's authenticated REST user endpoint returned HTTP 200. GigBid's read-only MCP client fetched `README.md` and `src/requests/api.py` from `psf/requests` on `main`. A disposable Docker portfolio indexed one repository document and returned it in a vector search. This smoke test used local hash embeddings. The Kaggle CSV supplies historical pricing data independently of the MCP portfolio feature.

## B. Retrieval and grounding

- Qdrant reported 588, 1,197 and 588 points across the 384-dimensional plain, multivector and contextual collections. The existing corpus and collections were preserved.
- The retrieval runner now uses all gold items in the Recall@5 denominator, deduplicates document IDs and records item-level results and no-evidence cases. The older results use a capped denominator.
- The [full BGE/Qdrant run without cross-encoding](../evals/results/rag_open_bge_qdrant_no_cross_encoder.json) covers 570 included dev records and four variants. V9 reached 0.5547 Recall@5 and 0.8099 nDCG@10, compared with V0 at 0.4382 and 0.6506. The raw JSON includes per-persona and per-category results.
- The [BGE cross-encoder follow-up](../evals/results/rag_open_bge_qdrant_24.json) evaluated six variants on 22 jobs. The longer CPU attempt left a [six-record checkpoint](../evals/results/rag_full_cross_encoder.jsonl). Coverage of the configured model remains limited.
- The [full TinyBERT cross-encoder benchmark](../evals/results/rag_full_tinybert.json) scored seven configurations on 570 common dev jobs with the existing BGE embeddings. The [paired hybrid comparison](../evals/results/tinybert_v3_paired_hybrid.json) found a 0.0617 nDCG@10 drop on jobs with gold evidence. Reproduce the run with `python -m evals.runners.cross_encoder --backend tinybert --with-ablations --output rag_full_tinybert`.
- The [runtime pilot](../evals/results/retrieval_bge_runtime_pilot.json) preserves the original BGE composition's 90-second Matcher timeout and retry on a matched job. The source configuration defaults to V9, which uses the BGE embeddings and skill graph. The original composition remains available as `best`. The running containers use their existing image configuration.
- The [matched V0 versus V9 comparison](../evals/results/retrieval_outcomes_open.json) covers 30 graph runs on 15 common jobs across three personas. All 17 drafts received GigSim outcomes and AI rubric scores. Both arms produced six replies. V9 reached 0.8317 nDCG@10 and 34.29 seconds proposal p95. A separate Portfolio MCP call using the new source configuration confirmed the V9 default.
- Historical [offline results](../evals/results/rag.json) and [ablations](../evals/results/ablation.json) use hash embeddings and lexical reranking. A diagnostic that paired NumPy with metadata from a Qdrant index was invalid and was stopped.
- Following the instructor clarification reported by the student, the [AI evaluation](../evals/results/judge_ai_review.json) compares two model raters on 30 anonymized proposals and tests 15 blind pairs in both orders. Unweighted kappa was 0.1196 and quadratic-weighted kappa was 0.2182. Twelve preferences were consistent and three were order-sensitive. The ratings are AI-generated. The [human review sheets](BLIND_REVIEW.md) remain available for optional follow-up.

## C. Graph workflows and model profiles

- The [PostgreSQL recovery run](../evals/results/postgres_worker_recovery.json) deliberately terminated a worker after GigSim accepted the proposal, then terminated its replacement after checkpointing and before updating the app tables. A third process recovered both the saved result and the approval state. GigSim contained one proposal, Connects dropped from 120 to 108, and a repeated resume was ignored.
- The architecture runner uses ReAct, the prebuilt supervisor and the hand-built graph. It counts invalid outputs and exceptions as decision errors and records usage and simulator score denominators.
- Groq's account model list included GPT-OSS 20B and 120B. The updated alternate profile uses GPT-OSS 20B throughout. The previous alternate Llama IDs were absent from the model list.
- The [matched 50-job architecture study](../evals/results/architecture_open_50.json) uses Groq, BGE embeddings and lexical reranking. ReAct made 37 correct decisions, the supervisor made one, and the hand-written graph made 47. The supervisor had 38 provider HTTP 400 responses and ten additional unusable decisions. The [20B-only hand graph](../evals/results/architecture_alt_50.json) made 45 correct decisions on the identical 50 jobs. Raw rows include cost, latency, unsupported claims and scoring coverage.

## D. Web

- The inbox now explains why Scout cannot start when no saved search is enabled. Onboarding already creates defaults for new accounts.
- The new Playwright case supplies an unavailable-marketplace health response and checks the queued-work banner and recovery. A process-level outage test is separate from that browser contract case.
- The TypeScript check passed. The isolated Scout and trace redaction regression tests passed. The initial Playwright run exposed the hard-coded Docker API hostname. The web config now respects `API_URL`.
- All seven browser cases passed across the suite and two targeted retries. The suite passed five cases, including approval, edit/reject, and the degraded-mode banner. Windows suspended network I/O during the first onboarding attempt. The run-viewer test raced the route transition and was corrected. Both cases passed independently on retry.

## E. Deployment and operations

- The existing API, worker, web, PostgreSQL, Redis, Qdrant, GigSim and MCP services were running in Docker. API and worker reported `MODEL_PROFILE=open` and a configured Groq credential.
- The previous API image contains a local `.env` file. The build context now excludes `.env`, environment variants and raw data. The running containers use their existing configuration. New Compose runs need a Groq credential supplied through the environment or a local env file.
- Trace redaction now permits non-negative numeric counters and masks other token-like fields, including a string written into a counter field. Redacted historical events cannot recover their original counters.
- The pin for Qdrant client 1.15.1 was tested against Qdrant 1.15.4 with a read-only 384-dimensional search. Concurrent cross-encoder runs caused a memory kill. The live API returned HTTP 200 after the benchmark processes were stopped.
- API, worker and web images built successfully from a working snapshot. The rebuilt API image was checked directly for the supervisor dependency and exclusion of `.env`. The final source includes additional fixes made while that build was running. The live API, worker and all dependencies passed the final service status check.
- Local checks exercise the source in isolation. The CI workflow includes the PostgreSQL recovery check against a disposable service. Hosted Actions remains pending because GigBid is still local.
- GitHub Actions, public deployment, reviewer login, public traces, the public write-up and the instructor's hidden test require an external environment or account.

## Portfolio extension

The [paired reply reanalysis](../evals/results/opening_strategy_paired_reply.json) uses 74 historical offline GigSim pairs. No pair changed its observed reply outcome between evidence-first and question-first. The exact paired test gave p = 1.0. See [the extension description](EXTENSION.md) and [the original observations](../evals/results/gigsim_outcomes.json).

The [engineering review](RD_REPORT.md), [technical write-up draft](TECHNICAL_WRITEUP.md), [blinded review pilot](BLIND_REVIEW_PILOT.md) and [dev failure taxonomy](../evals/results/failure_cases_dev.csv) accompany the raw results. The technical write-up includes the résumé bullet. The README includes a verified 30-second GIF from the isolated GigSim approval flow.

## Reproduction

Run these from the project root in an environment with the project dependencies and the synthetic dev data. Set the model provider credential privately for the open-model runners.

```powershell
python -m pytest -q
python -m evals.runners.tool_granularity --n 40 --output tool_granularity_repeat
python -m evals.runners.rag_eval --variants v0_naive,v1_decompose,v2_hybrid,v3_rerank,v9_skill_graph,best --output rag_repeat
python -m evals.runners.baselines --n 50 --output baselines_open_repeat
python -m evals.runners.judge --from-results evals/results/architecture_open_50.json evals/results/architecture_alt_50.json
```

Run `python -m evals.runners.ai_review` to reproduce the AI-only agreement and preference experiment. For optional human calibration, use `python -m evals.runners.judge --score` after reviewers have rated the blinded drafts. Keep evaluation concurrency low when using the BGE cross-encoder on an 8 GiB Docker VM. Open-model runs report provider response coverage and identify heuristic fallbacks.

For the matched retrieval-to-proposal run, set `MODEL_PROFILE=open`, `MARKETPLACE_MODE=gigsim`, and `MCP_TRANSPORT=inprocess`. Point `QDRANT_URL` at the BGE development indexes and supply the model provider credential privately. Run `python -m evals.runners.retrieval_outcomes --arms v0_naive v9_skill_graph` followed by `python -m evals.runners.results_table`. The benchmark checkpoints each job and arm and resumes with the same plan. GigSim scores the final draft through its evaluation endpoint. To reproduce the BGE runtime pilot, use `python -m evals.runners.retrieval_outcomes --output retrieval_bge_runtime_pilot --max-new-rows 3` with a fresh output name.

The ZIP contains the synthetic corpus and the evaluation evidence. The local Kaggle CSV and derived historical job records were excluded from the archive. If using that data in a reproducibility run, regenerate the local historical records with `scripts/prepare_kaggle.py` and record the import audit. The Playwright report and traces are under `apps/web/playwright-report` locally. The archive excludes traces, runtime environment files, and test artifacts.
