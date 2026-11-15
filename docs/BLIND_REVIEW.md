# Proposal review instructions

The [Proposal evaluation results](../evals/results/judge_ai_review.json) contain two model ratings for each of 30 proposals and 15 blinded pair comparisons judged in both orders. Unweighted Cohen’s kappa was 0.1196 and quadratic-weighted kappa was 0.2182. Twelve pair preferences survived reversal and three were order-sensitive. Agreement is between models from the same family.

Reproduce the AI evaluation with `python -m evals.runners.ai_review` under the configured Groq profile. The following materials remain available for an optional human follow-up.

The [unblinded matchup summary](../evals/results/judge_pairwise_matchups.json) groups the consistent votes and order-sensitive outcomes by the systems that produced each pair.

Use [the 30-item calibration sheet](../evals/datasets/judge_labels.csv) to record your own ratings. Read the job and the anonymized proposal, then fill the `human_overall` column with a score from 1 to 5. A 1 means unusable, 3 means usable after edits, and 5 means likely to earn a reply as written. Consider relevance to the job, specificity of the evidence, clarity, and professionalism.

Give each classmate a copy of [the 15-pair sheet](../evals/datasets/judge_pairwise_panel.csv). For each job, rate which draft would be more likely to earn a reply. Enter A, B, or Tie and give a brief reason. Collect reviewers' files independently.

Keep model scores and the blinding manifest out of reviewers' materials until their ratings are saved. After completing the calibration sheet, run `python -m evals.runners.judge --score` with the configured model profile to report Cohen's kappa. The initial results file contains the original model scores.
