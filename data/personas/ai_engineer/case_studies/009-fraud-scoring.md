---
id: "ai_engineer-case-009"
type: "case_study"
persona: "ai_engineer"
project: "fraud-scoring"
title: "Transaction fraud scoring"
skills: ["XGBoost", "scikit-learn", "FastAPI", "Docker", "AWS"]
date: "2024-09-10"
client_industry: "Fintech"
outcome: "delivered"
provenance: "synthetic"
---

# Transaction fraud scoring

## Context
A fintech client needed a real-time fraud score behind the payment API.

## What I did
- LightGBM.
- Classical models with cross-validated pipelines.
- Served it behind an async Python web service.
- Packaged every service into reproducible images.
- AWS.

## Result
The project blocked 62% of fraud value at a 0.4% false-positive rate with 40 ms latency.
