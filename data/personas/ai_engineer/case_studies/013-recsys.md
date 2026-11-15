---
id: "ai_engineer-case-013"
type: "case_study"
persona: "ai_engineer"
project: "recsys"
title: "Product recommendations"
skills: ["PyTorch", "FAISS", "Redis", "FastAPI"]
date: "2024-03-30"
client_industry: "E-commerce"
outcome: "delivered"
provenance: "synthetic"
---

# Product recommendations

## Context
A e-commerce client needed a two-tower recommender serving the product page.

## What I did
- PyTorch.
- An approximate nearest-neighbour index over embeddings.
- An in-memory cache and queue backend.
- Served it behind an async Python web service.

## Result
The project raised click-through on recommendations by 12% in a two-week test.
