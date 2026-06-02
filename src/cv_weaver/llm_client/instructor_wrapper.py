"""Lightweight LLM client for Ollama (local or cloud) with Pydantic validation.

Why not use `instructor` here?
- The cloud Ollama service (ollama.com) exposes the native Ollama API, not the
  OpenAI-compatible /v1/chat/completions path that instructor expects.
- instructor's `from_openai()` path requires an OpenAI client, which fails with 401
  against the cloud endpoint.
- This wrapper uses the native `ollama` Python client, then manually handles
  JSON extraction + Pydantic validation + retries — the same three things instructor
  does under the hood, just wired to the correct API.
"""

import json
import re
import time
from typing import Type, TypeVar

import ollama
from pydantic import BaseModel, ValidationError

from cv_weaver.config import Settings

T = TypeVar("T", bound=BaseModel)


class LLMRetryError(Exception):
    """Raised when the model fails to produce valid JSON after all retry attempts."""

    def __init__(self, model_name: str, response_model: str, attempts: int, last_error: str):
        self.model_name = model_name
        self.response_model = response_model
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"{model_name} failed to produce valid {response_model} after {attempts} attempt(s). "
            f"Last error: {last_error}"
        )


class LLMClient:
    """Native Ollama client with structured-output validation.

    Supports both local Ollama (default) and cloud Ollama (ollama.com) via
    the standard `OLLAMA_BASE_URL` and `OLLAMA_API_KEY` settings.
    """

    _MAX_RETRIES: int = 3

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = settings.generation_model

        # Structured Outputs experiment: tri-state flag
        # None = untried, True = supported, False = unsupported (fall back to json)
        self._schema_supported: bool | None = (
            True if settings.use_structured_outputs else False
        )

        headers: dict[str, str] = {}
        if settings.ollama_api_key and settings.ollama_api_key != "ollama":
            headers["Authorization"] = f"Bearer {settings.ollama_api_key}"

        host = str(settings.ollama_base_url).rstrip("/")
        if host.endswith("/v1"):
            host = host[:-3]

        self._client = ollama.Client(host=host, headers=headers, timeout=300.0)

    def _call_with_format(
        self,
        model_name: str,
        messages: list,
        fmt: str | dict | None = None,
    ) -> str:
        """Make a single streaming chat call and return the concatenated content.

        Wraps the ollama client call. The ``fmt`` parameter is only passed when
        ``settings.use_structured_outputs`` is True, since ``format='json'``
        can cause empty responses on some cloud models.
        """
        kwargs: dict = {"model": model_name, "messages": messages, "stream": True}
        if fmt is not None:
            kwargs["format"] = fmt
        stream = self._client.chat(**kwargs)
        content = ""
        for chunk in stream:
            content += chunk["message"]["content"]
        return content

    def chat_completion(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> T:
        """Send a prompt to the LLM and enforce structured output via Pydantic.

        Uses streaming to avoid httpx read-timeout on long generations.
        Retries up to 3 times if the model returns malformed JSON.

        When ``settings.use_structured_outputs`` is True, the first call for each
        response model will try passing the Pydantic JSON Schema to Ollama's
        ``format=`` parameter. If the endpoint rejects it, we fall back to
        unconstrained generation and remember the failure so future calls skip
        the trial.

        IMPORTANT — learned from kimi-k2.6 on Ollama Cloud:
        - `stream=True` is required: the timeout resets per chunk, so a 300s
          total generation does not trigger a ReadTimeout.
        - `options={"num_predict": N}` causes EMPTY output for this model.
          Do NOT add token caps via ollama options for cloud models.

        Args:
            prompt: The user-facing prompt text.
            response_model: A Pydantic BaseModel subclass describing the expected JSON schema.
            system_prompt: Optional override for the system prompt. If None, the
                default L1 system prompt from generator.prompts is used.

        Returns:
            An instance of `response_model` populated by the LLM output.

        Raises:
            LLMRetryError: If the model fails to produce valid JSON matching the
                schema after the configured retries.
        """
        from cv_weaver.generator.prompts import SYSTEM_PROMPT

        sys_msg = system_prompt if system_prompt is not None else SYSTEM_PROMPT
        model_name = model or self._model
        t0 = time.perf_counter()
        print(
            f"    [LLM] START {response_model.__name__:25s} "
            f"model={model_name} sys={len(sys_msg)} chars prompt={len(prompt)} chars"
        )

        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        # Determine which format value to use.
        # If structured outputs are enabled and we haven't confirmed the endpoint
        # doesn't support schemas, try the Pydantic schema first.
        use_schema = self._schema_supported is True  # True = try, False/None = don't
        schema = response_model.model_json_schema() if use_schema else None

        last_error = ""
        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                if use_schema and schema is not None:
                    content = self._call_with_format(model_name, messages, schema)
                else:
                    content = self._call_with_format(model_name, messages, None)

                # Guard against completely empty responses
                if not content.strip():
                    raise json.JSONDecodeError("Model returned empty output", "", 0)

                parsed = self._extract_json(content)
                result = response_model.model_validate_json(parsed)
                elapsed = time.perf_counter() - t0
                print(f"    [LLM] DONE  {response_model.__name__:25s} in {elapsed:.2f}s (attempt {attempt}, {len(content)} chars)")
                return result
            except ollama.ResponseError as exc:
                # Endpoint-level error (e.g., unsupported format parameter).
                # If we were trying schema, fall back to unconstrained generation
                # WITHOUT burning a retry attempt.
                if use_schema and schema is not None:
                    print(f"    [LLM] Schema format rejected by endpoint: {exc}. Disabling structured outputs.")
                    self._schema_supported = False
                    use_schema = False
                    schema = None
                    continue  # retry same attempt number with no format constraint
                # Otherwise it's a real endpoint error — raise it.
                elapsed = time.perf_counter() - t0
                print(f"    [LLM] FAIL  {response_model.__name__:25s} after {elapsed:.2f}s: {exc}")
                raise
            except (ValidationError, json.JSONDecodeError, KeyError) as exc:
                last_error = str(exc)
                print(f"    [LLM] RETRY {response_model.__name__:25s} attempt {attempt}/{self._MAX_RETRIES}: {last_error[:120]}")
                messages.append(
                    {"role": "user", "content": f"That was not valid JSON. Error: {last_error}. Please return ONLY raw JSON matching the schema exactly."}
                )
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                print(f"    [LLM] FAIL  {response_model.__name__:25s} after {elapsed:.2f}s: {exc}")
                raise

        elapsed = time.perf_counter() - t0
        print(f"    [LLM] FAIL  {response_model.__name__:25s} after {elapsed:.2f}s (exhausted retries)")
        raise LLMRetryError(
            model_name=model_name,
            response_model=response_model.__name__,
            attempts=self._MAX_RETRIES,
            last_error=last_error,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown fences and extract the raw JSON payload.

        Handles responses wrapped in ```json ... ``` or plain JSON.
        Also handles cases where the model adds conversational text
        before/after the fenced block.
        """
        text = text.strip()
        # Try to extract JSON from a markdown code fence first
        fence_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if fence_match:
            return fence_match.group(1).strip()
        # Fallback: if the text starts with { and ends with }, assume it's JSON
        text = text.strip()
        return text


def create_instructor_client(settings: Settings | None = None) -> LLMClient:
    """Factory function that creates an LLMClient from application settings.

    Args:
        settings: Optional Settings instance. If None, settings are loaded from `.env`.

    Returns:
        A configured LLMClient ready for chat_completion calls.
    """
    if settings is None:
        from cv_weaver.config import load_settings

        settings = load_settings()
    return LLMClient(settings)
