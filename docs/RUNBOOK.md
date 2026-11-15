# Runbook

## Local, no Docker, no API key (5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m scripts.generate_data && python -m scripts.seed
make web-install                                             # npm install in apps/web
python -m scripts.dev                                        # GigSim :8081, API :8000, web :3000
```
Open http://localhost:3000, create an account and pick a
portfolio. `MODEL_PROFILE=offline` needs no key: agents use deterministic heuristics and hashed
embeddings. It exercises every code path except real model calls.

## With open-weight models (the required profile)

```bash
pip install -e ".[models]"                  # BGE embeddings + reranker, CPU
export MODEL_PROFILE=open GROQ_API_KEY=...  # gpt-oss-20b for cheap nodes, gpt-oss-120b for writer/critic
python -m scripts.seed                      # re-index with real embeddings
```
`open_alt` (Llama 3.1 8B / 3.3 70B on the same provider) is the second configuration to compare.
`open_local` uses the compose `ollama` service (`qwen3:4b` / `qwen3:8b`), fully offline.

## Docker (everything)

```bash
docker compose -f infra/docker-compose.yml up --build
```
Web, API, arq worker, three MCP servers over HTTP, GigSim, Postgres (checkpointer + store + app
DB), Redis (queue), Qdrant (vectors). Add `--profile ollama` for local models.

## Scheduling

The worker's `tick` runs every 30 s and runs each user's saved searches that are due. Each search
has its own interval, floored by `marketplace.scout_interval_minutes`: **5 min on GigSim**,
**180 min in live mode**. Rationale for live mode: freelance posts stay open for days, the best
time to bid is within hours not minutes, and 8 polls a day per search keeps us far below any
reasonable API budget while respecting Upwork's automation guidance. A scouting pass fetches at
most `scout_max_new_per_run` new jobs; the rest wait for the next pass.

## Demonstrations for the viva

| What | How |
|---|---|
| Crash and resume | Approve nothing; wait for a draft in "Needs my approval". `docker compose kill api worker`, then `up -d`. Reload: the approval is still there (Postgres checkpoint). Approve: submitted once. `tests/integration/test_bid_graph.py::test_bid_path_pauses_for_approval_then_submits_once` also replays the submit node from checkpoint history and asserts Connects were spent once. |
| Kill the marketplace server | `docker compose stop mcp-marketplace` (or `gigsim`). The UI banner says "Marketplace unavailable"; jobs park as `queued`. `start` it again: `retry_queued` resumes them from their checkpoints. |
| Delete evidence, claim disappears | Settings -> Portfolio -> remove the item a claim cites -> job detail -> "Analyse again". The new draft cannot cite it; the verifier removes any sentence that still states its facts. |
| Policy change | Edit `gigsim/policy.yaml` `update:` and restart GigSim. Pricing reads Connects cost and the daily cap from the marketplace; Compliance reads the cover-letter limit from `get_policy`. No GigBid code changes. |
| Injected instruction ignored | Inbox -> a job with risk flag "prompt injection" -> job detail shows the removal notice; the draft never contains the canary. |

## Live Upwork mode

1. Settings -> Connected accounts -> Connect Upwork (OAuth 2.1 + PKCE against the official MCP server).
2. `python -m scripts.check_upwork` lists the server's tools; fix `marketplace.upwork.tool_map` if names differ.
3. Settings -> marketplace `upwork`. Live mode only reads and creates **drafts**; `submit_proposal`
   returns "awaiting confirmation on Upwork" and you confirm on the platform yourself.

## Secrets

Only from environment variables (`.env` locally, the host's secret store in deployment). `.env` is
git-ignored; `scripts/ci_checks.py` fails CI on committed keys. OAuth tokens are Fernet-encrypted
(`TOKEN_ENCRYPTION_KEY`). Reviewer credentials go in the private GCR comment only.
## Reviewer account

Set `REVIEWER_EMAIL` and `REVIEWER_PASSWORD` through the deployment environment before seeding a reviewer. The seed command leaves existing accounts in place. Share credentials through the private submission comment.

