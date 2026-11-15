# Data card

Every row GigBid uses is labelled with its provenance: `"provenance": "synthetic"`,
`"kaggle:<file>"`, `"user_upload"` or `"github:<user>/<repo>"`. Nothing real is mixed into the
evaluation gold labels.

## 1. Synthetic data (generated, committed)

`python -m scripts.generate_data --seed 7` regenerates all of it deterministically.

| Asset | Size | Where | Purpose |
|---|---|---|---|
| Personas | 3 (AI/ML engineer, full-stack developer, data analyst) | `data/personas/<id>/` | Portfolios the agents must ground claims in |
| Case studies | 20 per persona | `case_studies/*.md` | Main evidence; ~45% of skill mentions are *implied* (described, not named) and ~20% use an alias, so naive retrieval misses relevant evidence |
| Repositories | 8 per persona | `repos/<slug>/` | README is deliberately vague; the code names the libraries (tests multi-vector indexing) |
| Client reviews | 16 per persona | `reviews/*.md` | Talk about results, never name tools |
| Past proposals | 150 per persona, labelled won / replied / ignored | `proposals/*.md` | Outcome-aware ranking (V4) and outcome memory; outcome correlates with specificity |
| CV | 1 per persona (Markdown + PDF) | `cv.md`, `cv.pdf` | PDF loader |
| Historical jobs | 1,500 | `data/gigsim/jobs_historical.json` | Market pricing statistics |
| Live job stream | 158 (incl. 8 reposts) | `jobs_stream.json` | What the Scout sees; ~12% scams, ~10% planted injections, ~6% lowball |
| Dev set | 200 jobs per persona with gold labels | `evals/datasets/dev_<persona>.json` | All evaluations |
| Clients | ~360 | `clients.json` | Public history (payment verified, spend, hires, rating) |
| Hidden client preferences | per job | `hidden.json` | Never served by GigSim's API; used only by the simulated client |

**Dev set composition per persona:** 105 in-domain, 20 adjacent-domain, 20 off-domain, 20 scams,
15 planted injections (each with a unique canary token), 10 lowball budgets, 10 exact reposts.

**Gold labels** (`gold` in each dev row): `bid` (fit >= 0.6, budget at or above the floor, not a
scam), `evidence` (case studies / repos whose skill tags cover >= 2 required skills, graded by
overlap), `price_band`, `scam`, `injection` + `canary`, `kind`.

## 2. Historical pricing data

Real Upwork postings from the Kaggle datasets the course listed can be merged into GigSim's
**pricing history only**:

1. Download any of the datasets below and unzip the CSVs into `data/raw/`.
2. `python -m scripts.prepare_kaggle` -> `data/gigsim/jobs_historical_real.json`.

The local import audit records 53,058 source rows from `upwork-jobs.csv` and 3,338 selected jobs. The importer discarded records with unusable or ambiguous prices, removed out-of-domain posts and exact duplicates, and sampled at most 400 records per category using seed 7. It assumes USD because the CSV lacks a currency field. The audit records the source SHA-256 and counts by category. The category cap and skills-based filter limit representativeness.

The local `upwork-jobs.csv` matches the SHA-256 of the CSV in the official Kaggle download of Asaniczka's [Upwork Job Postings Dataset 2024 (50K Records)](https://www.kaggle.com/datasets/asaniczka/upwork-job-postings-dataset-2024-50k-records), version 1. Kaggle's dataset metadata lists the Open Data Commons Attribution License (ODC-By). The other job-posting datasets below cover the same general pricing use case.

| Dataset | Use | Licence |
|---|---|---|
| asaniczka / upwork-job-postings-dataset-2024-50k-records, v1 | budgets and hourly ranges by category | ODC Attribution License (ODC-By) |
| asaniczka / all-jobs-on-upwork-200k-plus | same, larger | check the Kaggle page |
| ahmedmyalo / upwork-freelance-jobs-60k | same | check the Kaggle page |
| asaniczka / freelance-contracts-dataset-1-3-million-entries | not used (contract-level; no job text) | — |
| sarveshchhetri / freelancer-success-earnings-and-churn-prediction | not used (freelancer-level aggregates) | — |
| adityammantri / trial-1 | fake-job detection; separate evaluation candidate | verify on the Kaggle page |

Verify each licence on its Kaggle page before redistributing anything; this repository does not
redistribute Kaggle data.

The source repository and Docker image exclude the Kaggle CSV and derived job text. To reuse the imported pricing history with a local Docker installation, mount the derived file read-only at `/app/data/gigsim/jobs_historical_real.json` in the GigSim service.

Real rows never enter the dev set, the live stream or the gold labels: they have no client, no
hidden preferences and no ground truth.

## 3. Limitations and circularity (read before citing numbers)

* **Gold evidence is defined from skill tags.** The skill-graph variant (V9) ranks by the same tags,
  so part of its lead on Recall/nDCG is by construction. The relative order of V0-V8 (which do not
  read tags) is the fairer comparison.
* **The simulated client is ours.** GigSim scores proposals on must-have skills, price, specificity,
  numbers, a generic opening and screening answers. GigBid was built knowing those features, so
  "GigBid vs a generic letter" overstates real-world lift. Comparisons *between GigBid variants* on
  the same jobs (paired) are more trustworthy than the absolute reply rate.
* Deviation from the brief: the simulated client decides with a transparent rule-based scorer plus
  seeded noise instead of an LLM, so outcome evals are free and repeatable.
* Synthetic text is template-generated: phrasing diversity is far lower than real posts, which flatters
  lexical retrieval (BM25) relative to real data.
