# ADR 0006: GigSim policy configuration

The assignment described a prospective November 2 update. The student confirmed that no updated rule was issued. The Classroom starter ZIP contains the original policy pack and a scaffold.

The bundled GigSim simulator has a synthetic example for evaluation reproducibility. The example adds four Connects at 20 proposals, caps daily proposals at 15, and limits cover letters to 1,800 characters.

**What had to change in GigBid:** nothing in agent code. GigSim's `policy.yaml` gained an `update:`
block; GigSim charges the surcharge in `connects`, enforces the cap and the length. GigBid already
reads Connects cost from the job, the cap from `get_connects_balance`, and the length limit from
`get_policy`, and the approval screen shows the surcharge from the dry-run preview.

The application reads platform rules at runtime and shows the policy cost in the approval preview.
