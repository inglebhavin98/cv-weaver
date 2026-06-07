"""Basic connectivity test for Ollama Cloud.

Verifies:
1. Client can connect to https://ollama.com
2. Authentication works
3. Model list is retrievable
4. A simple chat call succeeds
"""

import os
import sys

from dotenv import load_dotenv
from ollama import Client, ResponseError

load_dotenv(".env")

api_key = os.getenv("OLLAMA_API_KEY", "")
model = os.getenv("GENERATION_MODEL", "kimi-k2.6")

print(f"API Key present: {bool(api_key)}")
print(f"Model: {model}")
print()

client = Client(
    host="https://ollama.com",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=90.0,
)

# 1. List available models
print("--- 1. Listing available models ---")
try:
    models = client.list()
    for m in models.models:
        print(f"  - {m.model}")
except ResponseError as e:
    print(f"  Error listing models: {e.status_code} - {e.error}")
except Exception as e:
    print(f"  Unexpected error: {type(e).__name__}: {e}")

print()

# 2. Simple chat
print("--- 2. Simple chat test ---")
print(f"Sending chat to model: {model}")
try:
    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": "Say hello and your model name."}],
        stream=False,
    )
    print(f"Response: {response.message.content}")
except ResponseError as e:
    print(f"  ResponseError: {e.status_code} - {e.error}")
except Exception as e:
    print(f"  Unexpected error: {type(e).__name__}: {e}")

print()
print("Done.")
