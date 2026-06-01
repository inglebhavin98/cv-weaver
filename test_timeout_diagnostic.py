"""Quick diagnostic: test kimi-k2.6 with increasing prompt sizes."""

import os
import time
from dotenv import load_dotenv
from ollama import Client

load_dotenv(".env")

client = Client(
    host="https://ollama.com",
    headers={"Authorization": f"Bearer {os.getenv('OLLAMA_API_KEY')}"},
    timeout=90.0,
)

model = "kimi-k2.6"

# Test 1: Tiny prompt (we know this works)
print("--- Test 1: Tiny prompt ---")
try:
    t0 = time.perf_counter()
    r = client.chat(model=model, messages=[{"role": "user", "content": "Say hi."}], stream=False)
    print(f"OK in {time.perf_counter()-t0:.2f}s: {r.message.content[:50]}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print()

# Test 2: Medium prompt (~1,500 chars)
medium_prompt = """You are a resume writer. Read this story and extract ONE high-impact bullet point.

Story: I led a team of 5 engineers to redesign the payment system. We used Python and Redis. Latency dropped from 800ms to 120ms. The system handled 5x traffic during the next sale without issues.

Return ONLY a JSON object with these fields: action_verb, context, result, rendered_bullet."""

print("--- Test 2: Medium prompt (~1,500 chars) ---")
try:
    t0 = time.perf_counter()
    r = client.chat(model=model, messages=[{"role": "user", "content": medium_prompt}], stream=False)
    print(f"OK in {time.perf_counter()-t0:.2f}s: {r.message.content[:200]}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print()

# Test 3: Long prompt (~3,000 chars user + 3,000 chars system)
system = open("src/cv_weaver/generator/system_prompt_v1.xml").read()
story = """## Payment Orchestration Overhaul

Our payments system was hitting limits during flash sales. The checkout flow would degrade under 10x traffic spikes, and we were losing an estimated ₹2Cr per outage. I was asked to fix it.

I designed a circuit-breaker pattern with Redis-backed rate limiting and async queueing for non-critical payment steps. We split the monolithic payment handler into three microservices: gateway, orchestrator, and reconciliation.

P95 latency dropped from 800ms to 120ms. The system handled 5x traffic during the next Diwali sale without a single degradation. Post-implementation monitoring showed a 99.99% success rate.

_Skills_: Python, Redis, Kubernetes, gRPC
_Metrics_: P95 latency 800ms → 120ms, 99.99% success rate
_Team_: 3 engineers, 6 weeks
_Role_: Senior Software Engineer
"""

print("--- Test 3: Long prompt with system + story (~6,000 chars total) ---")
try:
    t0 = time.perf_counter()
    r = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": story},
        ],
        stream=False,
    )
    print(f"OK in {time.perf_counter()-t0:.2f}s: {r.message.content[:200]}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print()
print("Done.")
