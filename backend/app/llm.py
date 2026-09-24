"""LLM integration (T13 / FR04).

Provider-agnostic wrapper around local Ollama and any OpenAI-compatible HTTP
endpoint. The active provider is selected by ``settings.llm_provider``.

Usage (from the RAG layer)::

    client = get_llm_client()
    reply = client.complete(messages)          # messages: list of {"role": …, "content": …}

Error contract: any LLM-side failure raises ``LLMError`` so callers can return
a safe 503 to the user without leaking internal details.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the LLM call fails (timeout, model unavailable, etc.)."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMClient(ABC):
    """Minimal interface shared by all provider backends."""

    @abstractmethod
    def complete(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        """Send *messages* to the model and return the text reply."""


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------


class OllamaClient(LLMClient):
    """Calls a locally-running Ollama instance (``ollama`` PyPI package).

    The model name comes from ``settings.llm_model``; the base URL from
    ``settings.ollama_base_url``.  Both are configurable via ``.env``.
    """

    def __init__(self, *, model: str | None = None, timeout: float = 120.0, json_mode: bool = False) -> None:
        settings = get_settings()
        try:
            import ollama  # noqa: PLC0415 — lazy import, heavy at startup

            self._client = ollama.Client(host=settings.ollama_base_url, timeout=timeout)
            self._model = model or settings.llm_model
            self._json_mode = json_mode
        except ImportError as exc:  # pragma: no cover
            raise LLMError("ollama package is not installed") from exc

    def complete(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        settings = get_settings()
        try:
            response = self._client.chat(
                model=self._model,
                messages=messages,
                options={"temperature": temperature},
                **({"format": "json", "think": False} if self._json_mode else {}),
            )
            return response["message"]["content"].strip()
        except Exception as exc:
            logger.exception(
                "Ollama completion failed (model=%s, url=%s)",
                self._model,
                settings.ollama_base_url,
            )
            raise LLMError(f"Ollama error: {exc}") from exc


# ---------------------------------------------------------------------------
# OpenAI-compatible backend
# ---------------------------------------------------------------------------


class OpenAIClient(LLMClient):
    """Calls any OpenAI-compatible chat-completions endpoint via ``httpx``.

    Works with openai.com, Azure OpenAI, Groq, Mistral, etc.
    Set ``LLM_PROVIDER=openai``, ``OPENAI_API_KEY`` and optionally
    ``OPENAI_BASE_URL`` in ``.env``.
    """

    def __init__(self, *, model: str | None = None, timeout: float = 120.0, response_schema: dict | None = None) -> None:
        import httpx  # noqa: PLC0415

        settings = get_settings()
        if not settings.openai_api_key:
            raise LLMError(
                "OPENAI_API_KEY is not set. Add it to .env or use LLM_PROVIDER=ollama."
            )
        self._base_url = settings.openai_base_url.rstrip("/")
        self._api_key = settings.openai_api_key
        self._model = model or settings.llm_model
        self._response_schema = response_schema
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def complete(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        import httpx  # noqa: PLC0415

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if self._response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "query_rewrite", "strict": True,
                                "schema": self._response_schema},
            }
            payload["store"] = False
        try:
            resp = self._client.post(
                "/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException as exc:
            logger.error("OpenAI request timed out: %s/chat/completions", self._base_url)
            raise LLMError("LLM request timed out") from exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "OpenAI HTTP error %s from %s/chat/completions: %s",
                exc.response.status_code,
                self._base_url,
                exc.response.text[:200],
            )
            raise LLMError(f"LLM returned HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            logger.exception("Unexpected OpenAI client error")
            raise LLMError(f"LLM error: {exc}") from exc


# ---------------------------------------------------------------------------
# Mock / offline backend for testing
# ---------------------------------------------------------------------------


class GeminiClient(LLMClient):
    """Gemini GenerateContent client used for structured query rewriting."""

    def __init__(self, *, model: str | None = None, timeout: float = 120.0,
                 response_schema: dict | None = None) -> None:
        import httpx

        settings = get_settings()
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set. Add it to .env.")
        self._model = model or settings.llm_model
        self._response_schema = response_schema
        self._client = httpx.Client(
            base_url=settings.gemini_base_url.rstrip("/"),
            headers={"x-goog-api-key": settings.gemini_api_key},
            timeout=timeout,
        )

    def complete(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        import httpx

        payload = {
            "contents": [
                {"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]}
                for m in messages if m["role"] != "system"
            ],
            "generationConfig": {"temperature": temperature},
        }
        system = [ {"text": m["content"]} for m in messages if m["role"] == "system" ]
        if system:
            payload["systemInstruction"] = {"parts": system}
        if self._response_schema is not None:
            payload["generationConfig"].update(
                responseMimeType="application/json", responseJsonSchema=self._response_schema,
            )
        try:
            response = self._client.post(f"/models/{self._model}:generateContent", json=payload)
            response.raise_for_status()
            candidate = response.json()["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise LLMError("Gemini did not finish the response")
            result = "".join(part.get("text", "") for part in candidate["content"]["parts"]
                             if not part.get("thought")).strip()
            if not result:
                raise LLMError("Gemini returned no text")
            return result
        except LLMError:
            raise
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"Gemini returned HTTP {exc.response.status_code}") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("Gemini request timed out") from exc
        except Exception as exc:
            raise LLMError("Gemini request failed or returned an invalid response") from exc


class MockClient(LLMClient):
    """Offline mock LLM for testing without running Ollama or external API keys."""

    def complete(self, messages: list[dict], *, temperature: float = 0.2) -> str:
        system_content = next((m["content"] for m in messages if m.get("role") == "system"), "")
        user_content = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        if "--- Authorized document excerpts ---" in system_content:
            context = (
                system_content.split("--- Authorized document excerpts ---")[1]
                .split("--- End of excerpts ---")[0]
                .strip()
            )
            if context:
                return f"Based on your authorized company documents:\n\n{context}"
        return (
            f"Received: '{user_content}'. "
            "To enable live AI generation, start Ollama or set OPENAI_API_KEY in .env."
        )


# ---------------------------------------------------------------------------
# Factory / singleton
# ---------------------------------------------------------------------------

_singleton: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return the shared LLM client for the configured provider.

    Lazy-initialised on first call; subsequent calls return the same instance.
    Raises ``LLMError`` if the provider is unknown or misconfigured.
    """
    global _singleton
    if _singleton is None:
        settings = get_settings()
        provider = settings.llm_provider.lower()
        if provider == "ollama":
            _singleton = OllamaClient()
        elif provider == "openai":
            _singleton = OpenAIClient()
        elif provider == "mock":
            _singleton = MockClient()
        else:
            raise LLMError(
                f"Unknown LLM_PROVIDER={provider!r}. Supported: 'ollama', 'openai', 'mock'."
            )
        logger.info(
            "LLM client initialised: provider=%s model=%s",
            provider,
            settings.llm_model,
        )
    return _singleton
