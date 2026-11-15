# GigBid — implementation context

Status snapshot of this repository for the AI-4016 Assignment II (GigBid). Read this first if you
are picking the work up (you, a teammate, or a new AI session).

## 1. What the assignment is

Build GigBid: a multi-agent freelancer copilot that finds jobs, decides which are worth bidding on,
drafts proposals grounded only in the freelancer's real portfolio, prices them, handles client
replies, and never sends anything without human approval. Graded parts: A MCP tool layer (20),
B advanced RAG (20), C LangGraph multi-agent (25), D web UI (15), E production engineering (10),
portfolio + R&D report (10). A viva multiplier (0–1.0) applies to the total.

## 2. State: built and verified here

| Area | Status | Where |
|---|---|---|
| Synthetic data: 3 personas, 600-job gold dev set, GigSim seed | done, deterministic | `scripts/generate_data.py`, `docs/DATA_CARD.md` |
| GigSim simulator: jobs, scams, injections, duplicates, clients with hidden preferences, Connects, drafts→submit, events, threads, rate limits, 503s, policy update | done | `gigsim/` |
| Kaggle merge (real postings → pricing history only) | written, **not run** (no network to Kaggle here) | `scripts/prepare_kaggle.py` |
| A1 Portfolio MCP (tools, resources, prompts, read-only) | done, tested | `mcp_servers/portfolio/` |
| A2 Marketplace MCP (read/write, idempotency, dry_run, annotations, bearer auth, rate limit, audit log) | done, tested | `mcp_servers/marketplace/server.py` |
| A3 Workspace MCP (slots, tentative hold, email draft; local mock) | done, tested | `mcp_servers/workspace/` |
| A4 Upwork live adapter + OAuth 2.1/PKCE + encrypted tokens | written, **not exercised against a real Upwork account** | `adapters/upwork_live.py`, `apps/api/auth/upwork_oauth.py`, `scripts/check_upwork.py` |
| A5 GitHub MCP ingestion | written, **needs GITHUB_TOKEN; not run** | `rag/ingest/github.py` |
| A6 Per-agent allowlists, timeouts, retries, degraded mode | done, tested | `agent/mcp_client.py`, `config.yaml tools.allow` |
| A7 In-memory MCP tests + schema-snapshot test | done | `mcp_servers/*/tests`, `tests/contract/` |
| A7 MCP Inspector screenshots | **you** | `npx @modelcontextprotocol/inspector gigbid-portfolio-mcp --owner ai_engineer` |
| B1 Ingestion (Markdown, PDF CV, repos + code, uploads, incremental) | done | `rag/ingest/` |
| B2 Ten variants V0–V9 + shipped `best` | done, evaluated | `rag/variants/`, `rag/retriever.py` |
| B3 Claim verification + removal, before/after rates | done, tested (incl. a fabricated claim from a stub model being removed) | `rag/verify.py`, `agent/nodes/verifier.py` |
| B4 Retrieval, decision, injection, outcome, ablation evals | done (offline profile) | `evals/runners/`, `evals/results/` |
| B4 Calibrated LLM judge (Cohen's kappa on 30 self-labelled items) | written; **needs your 30 labels + an API key** | `evals/runners/judge.py` |
| B4 Blind human panel | **you** (classmates) | — |
| C1 Bid graph + conversation graph | done, tested | `agent/graphs/` |
| C2–C7 typed state, typed hand-offs, loop limits, interrupts, Postgres/SQLite checkpointer, retries, timeouts, fallback model, dead-letter, budgets | done, tested (crash-and-resume and exactly-once submit are tests) | `agent/` |
| R&D question A (tool granularity) | runner written; **needs an API key** | `evals/runners/tool_granularity.py` |
| R&D question C (ReAct vs supervisor vs graph) | runner written; **needs an API key** | `evals/runners/baselines.py` |
| D Web app: all 9 screens, typed generated client, SSE run stream, degraded banner, keyboard-accessible evidence popovers | done; typechecks; builds | `apps/web/` |
| D Playwright specs (5 files, 6 tests) | done, **all passing** against a local stack | `apps/web/tests/e2e/` |
| E1 arq worker + schedules; in-process fallback without Redis | done | `worker/` |
| E2 CI: lint, static checks, tests, smoke eval with thresholds, web build, Playwright | written | `.github/workflows/` |
| E3 Trace id UI→API→graph→MCP→audit log; per-node tokens/cost/latency; LangSmith with PII masking | done (LangSmith path needs a key) | `agent/tracing.py` |
| E4 Injection defence, PII masking in logs/traces, encrypted tokens, tenant scoping | done, tested | `agent/guardrails.py`, `tests/integration/test_api_flow.py` |
| E5 Declared budgets + measured | declared in config; measured offline | `config.yaml budgets.declared`, `evals/results/decision.json` |
| E6 docker compose (web, API, worker, 3 MCP servers, GigSim, Postgres, Redis, Qdrant, Ollama) | written, **not run here (no Docker in this sandbox)** | `infra/` |
| Change request (2 Nov policy) | done as config; stand-in values | `gigsim/policy.yaml`, `docs/adr/0006` |
| Signature extension X2 (A/B opening strategy) | done, measured: **null result** | `evals/results/experiment_ab.json` |

Test status at hand-off: **27 Python tests pass** (MCP servers, graphs, conversation flow, API flow,
tenancy, rate limiting, real-model code path via a stub, schema snapshot), **6/6 Playwright tests pass**,
`ruff` and `scripts/ci_checks.py` clean, smoke eval passes its thresholds.

Known flake: `test_conversation_graph.py::test_edit_with_contact_details_is_cleaned_before_sending`
failed once in ~6 runs (simulator event timing); it passed on every rerun.

## 3. What only you can do (in order)

1. **Get a free Groq key** (console.groq.com) and run with the required open profile:
   `pip install -e ".[models]"`, `MODEL_PROFILE=open GROQ_API_KEY=... make eval`. The offline numbers
   in the README are a pipeline check, not model results; the report needs the open-profile numbers.
   Also run `MODEL_PROFILE=open_alt` for the "two open configurations" comparison.
2. Run R&D A and C: `python -m evals.runners.tool_granularity`, `python -m evals.runners.baselines --n 50`.
3. Judge calibration: `python -m evals.runners.judge --export 30`, label the CSV yourself, then `--score`.
4. Push to a **public GitHub repo** with real, incremental commits (the brief warns that one giant
   commit near the deadline triggers a longer viva).
5. **Deploy** (Render blueprint in `infra/render.yaml`, or any host running the compose file); set
   secrets in the host, run `python -m scripts.seed`, put the reviewer password in the private GCR comment.
6. Turn on LangSmith (`LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`), produce and share three traces
   (skipped scam, approved proposal, critic loop) plus a crash-and-resume; link them in the README.
7. Publish the Portfolio MCP server (PyPI, or the documented `uvx`/Docker command in its README).
8. MCP Inspector screenshots → `docs/images/`; demo GIF → `docs/images/demo.gif`.
9. Record the 3-minute video (inbox → approved proposal, scam caught, injection ignored, client reply).
10. Write the R&D report PDF (≤10 pages; skeleton with the offline numbers in `docs/REPORT_DRAFT.md`)
    and the 1,200–1,800-word write-up. Use the real findings below.

## 4. Findings so far worth writing about (offline profile; re-check with `open`)

* **The skill graph (V9) ranks best on every persona**, but part of that is circular: gold evidence
  is defined from the same skill tags. Among tag-free variants, reranking (V3) and hybrid (V2) lead.
* **V9 never refuses**; only the corrective loop (V8) refuses on off-domain jobs. The shipped `best`
  combines graph + rerank + corrective, trading a little recall for refusals.
* **Requirement decomposition alone (V1) hurt** ranking vs V0 until the whole post was kept as one
  extra query with double weight — a negative result with a mechanism.
* **One injection template bypassed the defence** (`[[instruction]]`: a `\b` after `]]` never matches).
  Exposure went from 20% to 0% after the fix. Good failure-analysis entry.
* **Scam recall was 0.71** until a single policy-breaking flag (unpaid trial, gift cards) was made
  disqualifying instead of averaged into a 0.6 threshold; then 1.0.
* **Opening strategy (X2) made no measurable difference** (paired, same jobs, p≈0.25).
* **The "verification off" ablation shows no difference offline** because the template writer cannot
  invent claims; with a real model it will (the stub-model test shows a fabricated "15 years at Google"
  being removed). Run it under `open`.
* The rate limiter was originally per server instance, so in-process runs overran GigSim's 30/min
  account limit; fixed by one shared per-process limiter. Under load, work is parked as `queued` and
  resumes from checkpoints instead of failing.

## 5. Design rules a new contributor must keep

* No prompt text in Python; prompts are `agent/prompts/*.md` with a `version:` line (CI enforces).
* No model ids in Python; per-node models in `config.yaml` profiles (CI enforces).
* Only `agent/nodes/gateway.py` and the liaison `send` node reach write tools, and only after an
  approval; all writes carry idempotency keys derived from the thread id.
* Only `agent/memory/promotion_rules.py` decides what enters long-term memory.
* Platform rules (Connects cost, caps, length limits) are read from the marketplace at run time.

## 6. How to run (short)

```bash
pip install -e ".[dev]" && python -m scripts.generate_data && python -m scripts.seed
make web-install && python -m scripts.dev        # web :3000, API :8000, GigSim :8081
python -m pytest -q                               # backend tests
cd apps/web && npx playwright test                # with the stack running (set GIGSIM_RATE_LIMIT=300 MARKETPLACE_RPM=240 first)
make eval                                          # writes evals/results/ and the README table
```
