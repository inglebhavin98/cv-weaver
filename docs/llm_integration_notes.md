# LLM Integration Notes — Ollama Cloud

> **Purpose:** Operational reference for debugging Ollama Cloud integration issues.
> **Last updated:** 2026-05-31
> **Model tested:** `kimi-k2.6` on Ollama Cloud (`https://ollama.com`)

---

## 1. Client Setup

```python
from ollama import Client

client = Client(
    host="https://ollama.com",
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=150.0,  # seconds; see §3 below
)
```

**Key points:**
- Host must be `https://ollama.com`, **not** `https://ollama.com/v1`. The `/v1` path is for OpenAI-compatible clients; the native `ollama` library uses `/api/chat`.
- The library auto-reads `OLLAMA_API_KEY` from env, but explicit `headers` override it and are clearer.

---

## 2. Parameter Isolation Matrix

We ran a systematic grid to identify which `client.chat()` parameters affect `kimi-k2.6` behavior. The prompt was the exact L1 drafter prompt (~6,000 chars).

| `stream` | `format` | `options` | Time | Output | Verdict |
|----------|----------|-----------|------|--------|---------|
| `False` | — | — | **Timeout** | ❌ | `ReadTimeout` at 150s |
| `True` | — | — | **286s** | ✅ 1,817 chars raw JSON | **Baseline** |
| `True` | `json` | — | **474s** | ⚠️ 2,256 chars with ` ```json ` fences | Slower + fences |
| `True` | `json` | `num_predict: 2048` | **33s** | ❌ **0 chars** | **Deadly** |
| `False` | `json` | `num_predict: 2048` | **32s** | ❌ **0 chars** | **Deadly** |
| `False` | — | `num_predict: 2048` | **Timeout** | ❌ | Still times out |

**Conclusions:**
1. **`stream=True` is non-negotiable** for prompts that generate >1,000 tokens.
2. **`format='json'` is harmful** — adds fences and ~60% latency.
3. **`num_predict` kills output entirely** on this cloud model. Never use it.

---

## 3. Timeout Behavior

### `stream=False` (DO NOT USE)

The timeout is a **total-generation ceiling**. `httpx` starts the timer when the request is sent and stops it when the final byte of the response body arrives.

- Tiny chat (~20 tokens): 5s ✅
- Medium prompt (~80 tokens): 20s ✅
- Full drafter (~1,200 tokens): **>150s** ❌

### `stream=True` (REQUIRED)

The timeout is a **per-chunk read timeout**. The timer resets every time a chunk arrives from the server.

- Full drafter (~1,200 tokens): **286s total**, but chunks arrive every 1–3s → never times out ✅

**Recommended timeout:** 150s. This is high enough that even a slow first chunk won't trigger it, but low enough that a truly hung connection is caught quickly.

---

## 4. JSON Extraction

Because we do NOT use `format='json'`, the model sometimes wraps output in markdown fences:

```
```json
{ "candidates": [...] }
```
```

Our `_extract_json()` handles this:

1. Try regex: ` ```(?:json)?\s*\n?(.*?)\n?``` `
2. Fallback: assume the entire text is JSON if it starts with `{` or `[`

**Retry strategy:** If `model_validate_json` fails, append the error to the conversation and ask the model to return "ONLY raw JSON." This self-correction succeeds ~90% of the time on attempt 2.

---

## 5. Prompt Size vs. Generation Time

| Prompt | Tokens (est.) | Output | Time |
|--------|---------------|--------|------|
| "Say hi" | ~10 | ~20 | 5s |
| Medium drafter (~1,500 chars) | ~400 | ~80 | 20s |
| Full drafter + system (~6,000 chars) | ~1,500 | ~1,200 | **286s** |

**Rule of thumb:** For `kimi-k2.6`, time ≈ (input_tokens + output_tokens) × 0.1s per 100 tokens. The drafter is slow because it generates 3 candidates × 10 fields + reasoning = ~1,200 output tokens.

---

## 6. Debugging Checklist

If an LLM call fails, check in this order:

1. **Is `stream=True`?** If `stream=False`, large prompts will timeout.
2. **Is `num_predict` in `options`?** Remove it immediately — causes empty output.
3. **Is `format='json'`?** Remove it — slower and adds fences.
4. **Is the timeout ≥ 90s?** Cloud models need 90–150s for large structured outputs.
5. **Is the host `https://ollama.com` without `/v1`?** The native client uses `/api/chat`.
6. **Is the API key valid?** Test with a simple `client.list()` or tiny chat first.
7. **Is the model name correct?** Use exact tag, e.g., `kimi-k2.6` not `kimi-k2.5`.

---

## 7. Model Listing (Ollama Cloud, 2026-05-31)

Available models when queried via `client.list()`:

```
gemma3:4b, gemma4:31b, kimi-k2:1t, deepseek-v3.2, deepseek-v4-pro,
deepseek-v3.1:671b, rnj-1:8b, nemotron-3-super, cogito-2.1:671b,
qwen3-coder-next, minimax-m2.5, glm-4.6, gpt-oss:120b,
ministral-3:3b, ministral-3:8b, minimax-m2.1, glm-5.1,
qwen3-next:80b, gpt-oss:20b, devstral-2:123b, devstral-small-2:24b,
kimi-k2.5, kimi-k2.6, kimi-k2-thinking, deepseek-v4-flash,
qwen3.5:397b, glm-4.7, qwen3-coder:480b, qwen3-vl:235b-instruct,
qwen3-vl:235b, minimax-m2.7, gemma3:12b, gemma3:27b, glm-5,
nemotron-3-nano:30b, minimax-m2, ministral-3:14b, mistral-large-3:675b,
gemini-3-flash-preview
```

**Note:** Not all models have been tested with our pipeline. The behaviors above (`num_predict`, `format='json'`, `stream`) may vary across models. Test new models with `test_ollama_connection.py` before integrating.
