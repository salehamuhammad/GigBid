# ADR 0005: Long-term memory only through explicit promotion rules

`agent/memory/promotion_rules.py` is the only code that writes memory. A style pattern from the
user's edits is a candidate until seen in 3 distinct drafts; an outcome hint needs 5 proposals with
known outcomes in a category. Raw tool output, job text and client messages never reach memory;
free text is rejected if it looks like an instruction and PII is masked. Users can see and delete
every item in Settings; deleting a style rule marks it reverted so it is not silently re-learned.
