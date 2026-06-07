"""Test if format='json' works with kimi-k2.6 on Ollama Cloud."""

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

model = "kimi-k2.6"
prompt = "Return a JSON object with a single field 'answer' set to 'hello'."

# Test 1: No format, no stream
print("--- Test 1: No format, stream=False ---")
try:
    t0 = time.perf_counter()
    r = client.chat(model=model, messages=[{"role": "user", "content": prompt}], stream=False)
    print(f"OK in {time.perf_counter()-t0:.2f}s: {r.message.content[:200]!r}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

# Test 2: format='json', no stream
print("\n--- Test 2: format='json', stream=False ---")
try:
    t0 = time.perf_counter()
    r = client.chat(model=model, messages=[{"role": "user", "content": prompt}], stream=False, format="json")
    print(f"OK in {time.perf_counter()-t0:.2f}s: {r.message.content[:200]!r}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

# Test 3: format='json', stream=True (accumulate)
print("\n--- Test 3: format='json', stream=True ---")
try:
    t0 = time.perf_counter()
    stream = client.chat(model=model, messages=[{"role": "user", "content": prompt}], stream=True, format="json")
    content = ""
    for chunk in stream:
        content += chunk["message"]["content"]
    print(f"OK in {time.perf_counter()-t0:.2f}s: {content[:200]!r}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

# Test 4: No format, stream=True (accumulate) — same as our working diagnostic
print("\n--- Test 4: No format, stream=True ---")
try:
    t0 = time.perf_counter()
    stream = client.chat(model=model, messages=[{"role": "user", "content": prompt}], stream=True)
    content = ""
    for chunk in stream:
        content += chunk["message"]["content"]
    print(f"OK in {time.perf_counter()-t0:.2f}s: {content[:200]!r}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print("\nDone.")
