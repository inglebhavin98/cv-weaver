"""Quick test: does the drafter succeed on attempt 1 after prompt fix?"""

import sys, os, time
sys.path.insert(0, "src")

from dotenv import load_dotenv
from ollama import Client
from cv_weaver.generator.prompts import drafter_prompt, StoryExtraction, SYSTEM_PROMPT
from cv_weaver.llm_client.instructor_wrapper import LLMClient
from cv_weaver.config import load_settings

load_dotenv(".env")
settings = load_settings()

client = LLMClient(settings)

prompt = drafter_prompt(
    story_title="Payment Orchestration Overhaul",
    story_body="""Our payments system was hitting limits during flash sales. The checkout flow would degrade under 10x traffic spikes, and we were losing an estimated ₹2Cr per outage. I was asked to fix it.

I designed a circuit-breaker pattern with Redis-backed rate limiting and async queueing for non-critical payment steps. We split the monolithic payment handler into three microservices: gateway, orchestrator, and reconciliation.

P95 latency dropped from 800ms to 120ms. The system handled 5x traffic during the next Diwali sale without a single degradation. Post-implementation monitoring showed a 99.99% success rate.
""",
    story_skills=["Python", "Redis", "Kubernetes", "gRPC"],
    story_metrics=["P95 latency 800ms → 120ms", "99.99% success rate"],
    story_team="3 engineers, 6 weeks",
    story_role="Senior Software Engineer",
    context_paragraph="I joined when the platform was a monolith serving 1M users. Over 18 months, I led the backend team's efforts to re-architect core services, improve reliability, and cut infrastructure costs. The team grew from 4 to 12 engineers during my tenure.",
)

print("Testing drafter (one story only)...")
t0 = time.perf_counter()
try:
    result = client.chat_completion(prompt=prompt, response_model=StoryExtraction)
    elapsed = time.perf_counter() - t0
    print(f"\n✅ SUCCESS in {elapsed:.2f}s")
    print(f"   Candidates: {len(result.candidates)}")
    for i, c in enumerate(result.candidates, 1):
        print(f"\n   Candidate {i}:")
        print(f"     situation: {c.extended_context_situation[:60]}...")
        print(f"     task: {c.extended_context_task[:60]}...")
        print(f"     verb: {c.action_verb}")
        print(f"     bullet: {c.rendered_bullet[:70]}...")
        print(f"     metrics: {c.impact_metrics}")
        print(f"     skills: {c.skills_utilized}")
        print(f"     domain_tags: {c.domain_tags}")
except Exception as e:
    elapsed = time.perf_counter() - t0
    print(f"\n❌ FAILED after {elapsed:.2f}s: {type(e).__name__}: {e}")
