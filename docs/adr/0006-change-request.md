# ADR 0006: The 2 November platform policy update

**Change (stand-in values; replace with the instructor's if different):** crowded jobs (>= 20
proposals) cost 4 extra Connects; a daily cap of 15 proposals; cover letters at most 1,800 characters.

**What had to change in GigBid:** nothing in agent code. GigSim's `policy.yaml` gained an `update:`
block; GigSim charges the surcharge in `connects`, enforces the cap and the length. GigBid already
reads Connects cost from the job, the cap from `get_connects_balance`, and the length limit from
`get_policy`, and the approval screen shows the surcharge from the dry-run preview.

**Time taken:** policy file edit plus one test assertion. **What it says about the design:** rules
that come from the platform are read from the platform at run time, not copied into prompts.
