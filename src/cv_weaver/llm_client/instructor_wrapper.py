"""Thin factory wrapper around the `instructor` library for Ollama-backed LLMs.

This is the bridge between the application and the LLM provider.
It configures an OpenAI-compatible client pointing at a local Ollama instance,
then wraps it with `instructor` for structured Pydantic output validation.
"""

from typing import Type, TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

from cv_weaver.config import Settings

T = TypeVar("T", bound=BaseModel)


class InstructorClient:
    """Provider-agnostic LLM client backed by Ollama via the OpenAI compatibility layer."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = instructor.from_openai(
            OpenAI(
                base_url=str(settings.ollama_base_url),
                api_key=settings.ollama_api_key,
            )
        )
        self._model = settings.generation_model

    def chat_completion(self, prompt: str, response_model: Type[T]) -> T:
        """Send a prompt to the LLM and enforce structured output via Pydantic.

        Args:
            prompt: The user-facing prompt text.
            response_model: A Pydantic BaseModel subclass describing the expected JSON schema.

        Returns:
            An instance of `response_model` populated by the LLM output.

        Raises:
            instructor.exceptions.InstructorRetryException: If the model fails to
                produce valid JSON matching the schema after the configured retries.
        """
        return self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
        )


def create_instructor_client(settings: Settings | None = None) -> InstructorClient:
    """Factory function that creates an InstructorClient from application settings.

    Args:
        settings: Optional Settings instance. If None, settings are loaded from `.env`.

    Returns:
        A configured InstructorClient ready for chat_completion calls.
    """
    if settings is None:
        from cv_weaver.config import load_settings

        settings = load_settings()
    return InstructorClient(settings)
