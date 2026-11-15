# ADR 0002: Decisions and gates are deterministic; models write and judge

**Decision.** Skip / watch / bid, the Connects check, the critic's length check, compliance
redaction and the scam rule are code driven by `agent/config.yaml` and `data/policy_pack/rules.yaml`.
Models extract (JobSpec), judge evidence strength, write, critique and classify intent. A model can
add risk flags but never remove a rule-detected one; a verifier model can be stricter than the
numeric fact check but never more lenient.

**Why.** These decisions spend money or break platform rules when wrong, must be explainable in the
UI, and must change with policy without prompt edits (see ADR 0006).
