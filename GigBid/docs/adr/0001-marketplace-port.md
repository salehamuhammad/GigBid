# ADR 0001: One marketplace port, two adapters

**Decision.** Agents never call a marketplace directly. `agent/marketplace_port.py` defines one
`MarketplacePort` protocol; `GigSimAdapter` (REST) and `UpworkLiveAdapter` (official Upwork MCP
server over OAuth) implement it; the Marketplace MCP server is its only caller. Switching is
`MARKETPLACE_MODE`.

**Why.** The graph, prompts and evals stay identical between simulation and live mode, and live
mode's safety rule (drafts only) is enforced in one adapter instead of in every agent.

**Cost.** Upwork's tool names are mapped in config and verified at connect time; market statistics
are unavailable live, so pricing falls back to the floor rate and the job's own budget.
