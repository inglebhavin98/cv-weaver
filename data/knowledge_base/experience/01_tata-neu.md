---
file_id: 01_tata-neu
company: Tata Neu
position: Senior Software Engineer
date: Jan 2022 – Dec 2023
location: Bangalore, India
---

I joined when the platform was a monolith serving 1M users. Over 18 months, I led the backend team's efforts to re-architect core services, improve reliability, and cut infrastructure costs. The team grew from 4 to 12 engineers during my tenure.

## Payment Orchestration Overhaul

Our payments system was hitting limits during flash sales. The checkout flow would degrade under 10x traffic spikes, and we were losing an estimated ₹2Cr per outage. I was asked to fix it.

I designed a circuit-breaker pattern with Redis-backed rate limiting and async queueing for non-critical payment steps. We split the monolithic payment handler into three microservices: gateway, orchestrator, and reconciliation.

P95 latency dropped from 800ms to 120ms. The system handled 5x traffic during the next Diwali sale without a single degradation. Post-implementation monitoring showed a 99.99% success rate.

_Skills_: Python, Redis, Kubernetes, gRPC
_Metrics_: P95 latency 800ms → 120ms, 99.99% success rate
_Team_: 3 engineers, 6 weeks
_Role_: Senior Software Engineer

## Cache Layer Redesign

The product catalog API was our biggest bottleneck. Every page load triggered 40+ DB queries. The existing in-memory cache was node-local and caused thundering herd problems during deploys.

I proposed and built a distributed caching layer with Redis Cluster and cache-aside pattern. Added stampedes protection with probabilistic early expiration. Wrote a custom Django middleware to auto-instrument cache hit/miss ratios.

API response times dropped by 60%. Cache hit ratio stabilized at 94%. Most importantly, deploys no longer caused latency spikes because the cache was shared across all nodes.

_Skills_: Python, Redis, Django
_Metrics_: API response time ↓ 60%, cache hit ratio 94%
_Team_: 2 engineers, 8 weeks
_Role_: Senior Software Engineer

## Team Onboarding and Mentoring

When the team grew from 4 to 12, onboarding became a bottleneck. New hires took 3+ weeks to make their first meaningful code contribution. Documentation was scattered across Confluence, Notion, and README files.

I created a structured onboarding track: a 2-week curriculum with hands-on tasks in a staging environment, paired with senior engineer shadowing. I also wrote internal runbooks for the top 10 incident types.

New hire time-to-first-PR dropped from 21 days to 5 days. The runbooks reduced mean-time-to-resolution for common incidents by 40%. Two engineers I mentored were promoted to Senior within 18 months.

_Skills_: Python, Technical Writing, Mentoring
_Metrics_: Time-to-first-PR 21d → 5d, MTTR ↓ 40%
_Team_: 12 engineers (my mentees)
_Role_: Senior Software Engineer
