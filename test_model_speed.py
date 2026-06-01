"""Compare kimi-k2.5 vs kimi-k2.6 on the exact drafter prompt."""

import os
import time
from dotenv import load_dotenv
from ollama import Client

load_dotenv(".env")

client = Client(
    host="https://ollama.com",
    headers={"Authorization": f"Bearer {os.getenv('OLLAMA_API_KEY')}"},
    timeout=150.0,
)

system = open("src/cv_weaver/generator/system_prompt_v1.xml").read()

# Exact drafter prompt from prompts.py
from cv_weaver.generator.prompts import drafter_prompt

story = """## Payment Orchestration Overhaul

Our payments system was hitting limits during flash sales. The checkout flow would degrade under 10x traffic spikes, and we were losing an estimated ₹2Cr per outage. I was asked to fix it.

I designed a circuit-breaker pattern with Redis-backed rate limiting and async queueing for non-critical payment steps. We split the monolithic payment handler into three microservices: gateway, orchestrator, and reconciliation.

P95 latency dropped from 800ms to 120ms. The system handled 5x traffic during the next Diwali sale without a single degradation. Post-implementation monitoring showed a 99.99% success rate.

_Skills_: Python, Redis, Kubernetes, gRPC
_Metrics_: P95 latency 800ms → 120ms, 99.99% success rate
_Team_: 3 engineers, 6 weeks
_Role_: Senior Software Engineer
"""

prompt = drafter_prompt(
    story_title="Payment Orchestration Overhaul",
    story_body=story,
    story_skills=["Python", "Redis", "Kubernetes", "gRPC"],
    story_metrics=["P95 latency 800ms → 120ms", "99.99% success rate"],
    story_team="3 engineers, 6 weeks",
    story_role="Senior Software Engineer",
    context_paragraph="I joined when the platform was a monolith serving 1M users. Over 18 months, I led the backend team's efforts to re-architect core services, improve reliability, and cut infrastructure costs. The team grew from 4 to 12 engineers during my tenure.",
)

for model in ["kimi-k2.5", "kimi-k2.6"]:
    print(f"--- {model} ---")
    for attempt in range(1, 4):
        try:
            t0 = time.perf_counter()
            r = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
            elapsed = time.perf_counter() - t0
            print(f"  Attempt {attempt}: OK in {elapsed:.2f}s ({len(r.message.content)} chars)")
            print(f"  Preview: {r.message.content[:120]}...")
            break
        except Exception as e:
            print(f"  Attempt {attempt}: FAIL {type(e).__name__}: {str(e)[:80]}")
    print()

print("Done.")
