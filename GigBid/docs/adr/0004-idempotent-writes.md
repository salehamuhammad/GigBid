# ADR 0004: Exactly-once writes through idempotency keys derived from the thread

Every write tool requires an `idempotency_key`; the Marketplace server stores key -> result and
replays it. Keys are derived from the LangGraph thread id (`draft:<thread>:<sha(text,bid)>`,
`submit:<thread>`, `msg:<thread>:<client message id>`), so a crash after the marketplace accepted a
submission, a node retry, a redelivered queue task or a double click can never submit twice or
spend Connects twice. Approvals are claimed with a conditional status update (`pending -> processing`).
