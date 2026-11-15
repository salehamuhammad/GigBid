# GigBid

AI-4016 R&D engineering review · 15 November 2026

Evidence draft for the local checkout. The student reported that the instructor accepts AI-only proposal evaluation. The instructor's hidden evaluation and external deployment are pending.

## 1. Workflow and constraints

GigBid helps a freelancer choose which jobs to pursue and assemble evidence for an application. The worker scouts saved searches and scores jobs. The freelancer decides every proposal and message that leaves the system. A marketplace write follows a LangGraph approval interrupt and uses an idempotency key derived from the thread. GigSim provides the development marketplace. The declared p95 budgets are 12 seconds for job analysis and 45 seconds for a proposal. The corresponding cost budgets are USD 0.002 and USD 0.01 per item. These are design targets from agent/config.yaml.

## 2. Architecture

The web client uses FastAPI and server-sent events. The API writes user state to PostgreSQL and enqueues jobs through Redis. The worker runs the bid and conversation graphs. Job Analyst, Risk Assessor and Fit Matcher run in parallel. Pricing, Writer, claim verification, Critic and Compliance prepare work for approval. Client Liaison classifies replies and uses Workspace tools for interview slots. An adapter behind the Marketplace port selects GigSim or Upwork. Portfolio MCP reads evidence through an owner-scoped retriever. Architecture diagrams are generated from the graphs in docs/graphs.

## 3. Tool design experiment

We expected richer tool descriptions to improve first-turn tool and argument selection. Forty labeled tasks were presented to GPT-OSS 120B under each of three tool surfaces. Tasks covered job details, client history, market statistics, portfolio evidence and Connects balance. The richer descriptions reached 92.5% tool selection and 82.5% argument accuracy. Terse same-granularity tools reached 85% and 77.5%. The coarse tools, with a server-level action and JSON-encoded arguments, reached 70% and 67.5%. Token averages were approximately 1,072, 781 and 532 among 39, 40 and 32 measured responses, respectively. Earlier coarse schemas elicited more provider errors. Their token counts are sparse. The final results are in evals/results/tool_granularity_open_final_40.json.

## 4. Evidence retrieval

The current runner divides the number of gold items in the first five unique results by the full gold set size. On 570 records after duplicate exclusion, mean persona Recall@5 and nDCG@10 were 0.4382 and 0.6506 for naive dense, 0.4036 and 0.6061 for decomposition, 0.4900 and 0.7144 for hybrid, and 0.5547 and 0.8099 for the skill graph. Of the 570 records, 461 had gold evidence and 109 had none. All four variants returned evidence for all 109 negative cases. The raw file evals/results/rag_open_bge_qdrant_no_cross_encoder.json records each query and category breakdown. The development labels share skill tags with parts of the retriever, which can favor the skill graph.

The CPU benchmark used the MS MARCO TinyBERT-L2-v2 ONNX cross-encoder with the existing BGE embeddings and Qdrant indexes. It scored seven configurations on the same 570 dev jobs, for 3,990 runs. The TinyBERT reranking variant reached 0.4294 Recall@5 and 0.6528 nDCG@10. On the 461 positive jobs, its mean nDCG@10 was 0.0617 lower than the matched hybrid baseline, with a paired bootstrap 95% confidence interval of -0.0755 to -0.0473. The full composition retained the BGE corrective threshold and refused all 109 negative jobs, but achieved only 0.1245 nDCG@10. Removing correction raised nDCG@10 to 0.7511 and dropped negative refusal accuracy to zero. The fixed threshold and cross-encoder choice both affect the retrieval and refusal results. See evals/results/rag_full_tinybert.json and evals/results/tinybert_v3_paired_hybrid.json.

The configured BGE cross-encoder remains characterized on a 22-job exploratory comparison. Hybrid reached 0.7117 nDCG@10, BGE reranking reached 0.5759, and the configured composition reached 0.6330. All six variants returned evidence on the five negative jobs. A checkpoint from the longer CPU attempt preserves six scored records. The 570-job results apply to TinyBERT. See evals/results/rag_open_bge_qdrant_24.json and evals/results/rag_full_cross_encoder.jsonl.

The matched outcome study tests whether the skill graph's stronger full-set retrieval carries through to proposal grounding and simulated replies. Its three-arm runtime pilot hit the BGE Matcher's 90-second node timeout and ended after a retry at 182.6 seconds on the first job. The saved pilot records the failure with the V0 and V9 runs on the same job in evals/results/retrieval_bge_runtime_pilot.json. The V0 and V9 comparison assigns the same fixed jobs to both arms, rotating order with a fixed simulator draw per job. Each graph runs to approval or termination. The simulator scores drafts that reach approval, using their price and screening answers. Proposal latency and estimated model cost cover graph execution through the approval gate. The AI judge's low calibration agreement makes the rubric score exploratory.

| Metric | V0 naive dense | V9 skill graph (selected) |
|---|---|---|
| Recall@5 | 0.6500 | 0.8000 |
| MRR | 0.9028 | 0.9167 |
| nDCG@10 | 0.6428 | 0.8317 |
| Unsupported claims per cover letter | 0.25 | 0.22 |
| AI rubric score /5 | 4.25 | 4.44 |
| Replies per scored draft | 6/8 (75.0%) | 6/9 (66.7%) |
| Replies per assigned job | 6/15 (40.0%) | 6/15 (40.0%) |
| Proposal p95 (s) | 40.48 | 34.29 |
| Estimated USD per proposal | 0.008217 | 0.008533 |
| Drafts per assigned job | 8/15 | 9/15 |

V9 improved nDCG@10 for each persona. V0 to V9 was 0.6401 to 0.7785 for AI engineering, 0.5892 to 0.8901 for full-stack, and 0.6992 to 0.8264 for data analysis. Both returned evidence for every no-gold job in the sampled retrieval check. Both produced six replies and three hires across the 15 assigned jobs. The paired bootstrap 95% interval for reply-rate difference was -26.67 to +26.67 percentage points. Six job pairs produced scored proposals in both arms. The higher retrieval scores therefore support evidence discovery, with no observed gain in total replies on this sample. Both arms ran on the same Docker snapshot and primary Groq models. Its fallback model differed from the current source, and there were three heuristic fallback calls for V0 and one for V9. Raw job-type, persona, timing, token and cost results are in evals/results/retrieval_outcomes_open.json.

Ship V9 Skill Graph with the existing BGE embeddings and retain the BGE reranking composition as the named best experiment. V9 led the full retrieval study and reached approval one additional time in the matched sample. Its proposal p95 stayed within 45 seconds, and estimated model cost stayed under USD 0.01 per proposal. It cost slightly more than V0 per proposal. The original independent cover-letter check flagged two claims in each arm. A targeted V9 rerun found a claim that extended live time-to-hire reporting to real-time monitoring of attrition and hiring. The evidence supported live time-to-hire reporting specifically. The verifier now normalizes typography, checks exact numerical facts, and requires explicit evidence for real-time operation. See evals/results/retrieval_grounding_recheck.json for the targeted rerun. The matched results in the table retain the original measurements.

## 5. Multi-agent graphs

The ReAct, prebuilt supervisor and hand-built graph ran on the same 50 jobs with BGE embeddings and lexical reranking. ReAct made 37 correct decisions, the first supervisor run made one, and the hand-built graph made 47. The supervisor returned 48 failed or unusable decisions. A sequential tool-call retry on the same jobs made ten correct decisions with 39 failed or unusable outputs. The GPT-OSS 20B-only hand graph made 45 correct decisions. The raw records include unsupported claims, score coverage, estimated cost and latency in evals/results/architecture_open_50.json, architecture_alt_50.json and supervisor_open_sequential_50.json.

On 15 matched proposal-quality jobs per arm, independent claim checking found 2 unsupported claims among 30 claims reaching approval with verification enabled, and 10 among 43 with verification disabled. Seven and nine jobs respectively reached approval, so the pooled claim rates are conditional on reaching that stage. The AI review compared two GPT-OSS model raters on 30 blinded drafts. Unweighted Cohen's kappa was 0.1196 and quadratic-weighted kappa was 0.2182. Twelve of 15 pair preferences were consistent across reversed ordering. Low agreement limits confidence in the AI scores. See evals/results/proposal_quality_open.json and judge_ai_review.json.

## 6. Policy change

The policy pack is data-driven. The student confirmed that the prospective November 2 update was never issued. ADR 0006 documents the synthetic simulator example used in development and its effect on the dry-run preview. Pricing and Compliance read live policy values through the Marketplace port.

## 7. Signature extension

The stored offline X2 study compares evidence-first and question-first openings on 74 matched GigSim jobs. Both observed reply rates were 52.7%, with no discordant binary reply outcomes. The exact paired test gives p = 1.0. Mean reply probability was 0.0011 higher for question-first, with a paired bootstrap interval from 0.0000 to 0.0034. A single pair changed score. The binary result describes this synthetic outcome run. See evals/results/opening_strategy_paired_reply.json and gigsim_outcomes.json.

## 8. Failure analysis

Provider rejections affected the first coarse tools. A simplified argument envelope recovered most of those tasks. One local retrieval diagnostic paired a NumPy backend with Qdrant metadata and yielded empty dense results. It was stopped and excluded. Concurrent cross-encoder runs exceeded the Docker memory budget. The live API returned HTTP 200 after stopping both runs. The dev job taxonomy in evals/results/failure_cases_dev.csv includes missed evidence, incorrect bid decisions and provider tool errors, each tied to an observed run and a comparison or retry.

## 9. Safety and platform respect

The worker runs GigSim by default. Live Upwork writes are draft actions behind a separate approval flow. User-scoped tools, idempotent writes, the policy guard and a prompt-injection quarantine limit inappropriate action. The trace redactor preserves numeric usage metrics and masks credential fields. Docker build contexts exclude local runtime credentials. Seven browser cases passed across the isolated main run and targeted retries. A disposable PostgreSQL worker recovered after two deliberate crashes and produced one GigSim proposal with a single Connects debit from 120 to 108. OAuth draft-only behavior passed local contract tests and Upwork metadata was reachable. The live account-authorized draft check was unavailable because GigBid had no connected Upwork account. Authenticated GitHub MCP ingestion fetched and indexed Requests README and source files.

## 10. Hidden evaluation and reproducibility

Hidden test evidence comes from the instructor's evaluation. The local tests and benchmark runs are indexed in docs/TECHNICAL_COMPLETION_STATUS.md. Historical pricing uses Asaniczka's Upwork Job Postings Dataset 2024, version 1, under ODC-By. The local CSV matches the official Kaggle download by SHA-256. Dev and simulator labels are synthetic. The public reviewer environment and submission links are pending.
