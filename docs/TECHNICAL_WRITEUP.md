# Why the smallest tool menu was the hardest to use

When a freelancer asks GigBid how many Connects they have left, the model needs one read from the marketplace. Connects are the credits a proposal can spend. A similarly simple request for portfolio proof involves an evidence search with the right requirement. These are small actions before a more consequential workflow that discovers jobs, drafts proposals and asks a human to approve them. I used those actions to test whether a model can choose a tool and supply the right arguments.

The surprising part was how much of the result came down to the shape of the tool call. The engineering temptation was to consolidate server operations behind one generic tool per server. That reduces the number of names in the prompt and makes one endpoint appear to cover a whole capability. It also creates a second selection problem inside a single tool. The model must pick a server, name one of its operations and encode an object with arguments appropriate for that operation. Each of those choices can fail even when the model understands the freelancer's request.

## Where the token savings went

I ran 40 labeled tasks through three tool surfaces on GPT-OSS 120B through Groq. The task set included marketplace job details, client history, typical pay for a category, portfolio evidence and the Connects balance. In each trial I captured the model's first tool call. The expected tool and the requested fields came from the task labels, with matching rules for free-text evidence requirements. The same task IDs ran under each surface. This measures dispatch and argument preparation at the first turn, before any tool returns a result.

The first two surfaces exposed individual read operations. One gave them terse descriptions derived from their names. The other used the shipped MCP descriptions. The third surface grouped operations by server. In the final run, the model used the shipped descriptions to choose the correct operation for 37 of 40 tasks and meet the expected argument checks for 33. The terse descriptions yielded 34 correct selections and 31 correct arguments. The simplified coarse tools yielded 28 correct selections and 27 correct arguments. These are observed results for this 40-task set. The tasks include repeated intents with different inputs, so the sample offers more evidence about these intents than about the wider marketplace.

The measured token averages were roughly 1,072 for the shipped descriptions, 781 for the terse ones and 532 for the coarse tools. The provider reported usage for 39, 40 and 32 trials, respectively. A provider rejection with unavailable usage has an unknown token count. Omitting it from the usage mean and keeping it in the accuracy denominator leaves both figures interpretable. For the coarse arm, the mean describes the measurable requests and should be read alongside the error count.

## When an integration error looks like a model error

The earliest coarse grouping was particularly fragile. It used a nested generic argument object. Twenty-eight of its 40 attempts received HTTP 400, and only five selected the expected operation. An experiment log containing a single accuracy percentage would hide the difference between a plausible call rejected at the provider boundary and a response that chose the wrong operation. It would also make the coarse tools look like an efficient option if missing usage were counted as zero.

I tried a flatter typed representation before settling on a small schema with string fields for the operation name and its JSON-encoded arguments. The runner decodes the second field, checks that it is an object and compares the expected values. The simplified representation improved observable task completion in a repeat run on the same 40 tasks. It still imposed an extra encoding step and produced fewer correct calls than either individual-operation surface. Both earlier runs are retained, so the change in protocol and the size of the provider acceptance problem are visible.

The result affects how I design the boundary between an agent and an API. The Marketplace port can offer one internal interface with several methods. That interface governs adapter selection and makes GigSim interchangeable with a live provider inside the application. The model-facing MCP boundary can expose specific operations with their own descriptions and schemas. Those decisions have different customers. The port serves the application code that owns the integration, and the MCP schema serves the model and tool hosts that must choose actions reliably.

## A smaller retrieval result still needs a refusal policy

The same lesson surfaced in GigBid's evidence search. The system retrieves items from the freelancer's portfolio before writing any experience claim. A better ranking brings relevant work closer to the top, but the Writer also needs a way to handle jobs for which the freelancer has no evidence. I compared four non-cross-encoded retrieval variants on the same 570 eligible development records using BGE embeddings and Qdrant. Across personas, naive dense retrieval reached 0.4382 Recall@5 and 0.6506 nDCG@10. The skill-graph variant reached 0.5547 and 0.8099. The improvement is measured against gold items whose labeling also uses skills, so related signals in the test labels and the skill graph can favor that variant.

The negative cases taught a different lesson. Each of the four methods returned evidence for all 109 jobs without labeled evidence. A high-ranked item can be the closest available project even when it provides little support for a particular requirement. Downstream checks need to distinguish a related document from support for a specific claim. GigBid includes a corrective refusal step and a claim verifier for that reason. The four-way result establishes a ranking improvement and gives a clear reason to measure refusal and claim quality separately. The later proposal evaluation and matched verifier trial examine draft quality and grounding. Weak agreement between model raters and the use of simulated replies limit how far those results generalize.

## What I would measure before switching a production workflow

A tool selection benchmark records intent, provider acceptance and schema quality together. I would keep a short suite of real calls for each provider, retain the original validation errors, and count model outputs that cannot be parsed. I would also track time and cost by customer action rather than by prompt alone. A cheaper first tool call can require a retry or force the user to intervene, so it can still increase the cost of completing the task.

For actions like submitting a proposal, the human approval gate is a separate boundary from the model's tool choice. GigBid's model can draft, while the approval flow determines when the write can occur. The browser test exercised the GigSim approval path and observed one submission. The related engineering work includes showing Connects cost before approval, scoping tool access and using a stable idempotency key for the eventual marketplace write. This lets the read-only experiment vary tool design without adding risk to the submission path.

The same job may mention a tool by name, describe it indirectly or ask for an outcome that needs several tools. The first-turn study mostly covers requests with one expected operation. A production evaluation would add requests with multiple valid routes and measure whether each route reaches a grounded answer. That would test the planning benefit of a tool surface alongside the dispatch accuracy measured here.

The project keeps per-task measurements in `evals/results/tool_granularity_open_final_40.json` and per-job retrieval measurements in `evals/results/rag_open_bge_qdrant_no_cross_encoder.json`. These records let another developer see which inputs benefited from richer descriptions and repeat the study with a different provider, description set or portfolio.

## Résumé bullet

Built a LangGraph freelancer copilot with MCP tools, portfolio-grounded retrieval and human-approved GigSim submissions.  
Measured 92.5% tool-selection accuracy over 40 tasks and raised Recall@5 from 0.4382 to 0.5547 on a 570-record retrieval benchmark.
