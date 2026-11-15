---
id: "fullstack_dev-case-005"
type: "case_study"
persona: "fullstack_dev"
project: "marketplace-api"
title: "Marketplace back-end API"
skills: ["FastAPI", "PostgreSQL", "Docker", "AWS", "CI/CD"]
date: "2024-08-03"
client_industry: "Marketplace"
outcome: "delivered"
provenance: "synthetic"
---

# Marketplace back-end API

## Context
A marketplace client needed a versioned REST API with rate limiting and audit logs.

## What I did
- FastAPI.
- A relational store with proper indexes and migrations.
- Packaged every service into reproducible images.
- AWS.
- CI/CD.

## Result
The project p95 latency of 85 ms at 400 requests per second.
