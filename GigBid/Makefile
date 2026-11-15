.PHONY: install dev test eval eval-smoke seed demo lint data web-install gen-api table
PY ?= python

install:
	$(PY) -m pip install -e ".[dev,models]"

data:            ## generate the synthetic corpora, GigSim seed and dev set
	$(PY) -m scripts.generate_data

seed: data       ## create DB tables, reviewer account and build the RAG indexes
	$(PY) -m scripts.seed

dev:             ## run GigSim + API (+ in-process MCP and worker) and the web app
	$(PY) -m scripts.dev

test:
	$(PY) -m pytest -q

lint:
	ruff check .
	$(PY) -m scripts.ci_checks

eval:            ## full evaluation; writes evals/results/*.json and refreshes the README table
	$(PY) -m evals.runners.rag_eval
	$(PY) -m evals.runners.decision_eval
	$(PY) -m evals.runners.gigsim_outcomes
	$(PY) -m evals.runners.injection_eval
	$(PY) -m evals.runners.ablation
	$(PY) -m evals.runners.results_table

eval-smoke:      ## 30-job smoke eval with failure thresholds (used by CI)
	$(PY) -m evals.runners.smoke --jobs 30

table:
	$(PY) -m evals.runners.results_table

demo:            ## one grounded proposal for one GigSim job, printed to the terminal
	$(PY) -m scripts.demo

web-install:
	cd apps/web && npm install

gen-api:         ## regenerate the typed TS client from FastAPI's OpenAPI schema
	$(PY) -m scripts.export_openapi && cd apps/web && npm run gen:api
