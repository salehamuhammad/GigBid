# Signature extension X2

GigBid evaluates an evidence-first opening and a question-first opening on the same eligible GigSim jobs. Both use the same user's portfolio and approval workflow. A generic cover letter provides a reference arm. Run the paired simulator study with `python -m evals.runners.gigsim_outcomes`.

The existing [offline study](../evals/results/gigsim_outcomes.json) uses 74 matched jobs. Both proposal strategies produced the same observed simulator reply rate, 52.7%. The question-first mean reply probability exceeded evidence-first by 0.001. The stored exact sign test uses the per-job reply probabilities. A test on observed replies uses only pairs whose binary reply outcomes differ. These measurements describe GigSim's scoring model and the offline draft generator.
