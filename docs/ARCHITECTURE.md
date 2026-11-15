# GigBid architecture

The Next.js app calls FastAPI for account data, portfolio management, scouting and approvals. FastAPI stores user state in PostgreSQL and queues long-running jobs through Redis. The ARQ worker streams graph events into the run timeline. PostgreSQL also stores graph checkpoints and promoted memory. The initial configuration and local setup are described in [the runbook](RUNBOOK.md).

## Bid workflow

[Bid graph](graphs/bid_graph.mmd)

- Scout runs each user's saved searches, deduplicates posts and queues new jobs.
- Job Analyst structures requirements, Risk Assessor checks the post and client history, and Fit Matcher finds portfolio evidence. The graph fans out to all three with LangGraph `Send`.
- A decision node combines the findings. Pricing uses market data, the user's floor and Connects budget for jobs routed to drafting.
- Writer uses retrieved evidence. The claim verifier reviews the draft before Critic, which can request up to two revisions. Compliance checks the resulting text against the policy pack.
- A LangGraph interrupt pauses execution for human approval. The submit path uses an idempotency key derived from the graph thread.

## Conversation workflow

[Conversation graph](graphs/conversation_graph.mmd)

Client Liaison loads the thread, classifies the newest message and asks the Workspace MCP server for calendar slots when relevant. It drafts a reply and runs compliance before interrupting for approval. On resume, approved writes go through the Marketplace or Workspace MCP servers. The memory promotion rules govern which edits and outcomes can influence future drafts.

## Tools and retrieval

Each node has an allowlist in `agent/config.yaml`. The Marketplace port selects GigSim or the Upwork adapter. Portfolio MCP exposes evidence search and read-only resources. The indexed metadata binds evidence to its owner. Retrieval can combine Qdrant cosine search, BM25, a skill graph and cross-encoder reranking. See the [tool catalogue](TOOLS.md), [data card](DATA_CARD.md) and [design decisions](adr/).
