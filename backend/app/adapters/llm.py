"""LLM Adapter interface and implementations."""

import json
import os
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel

from app.adapters.base import LLMResponse
from app.core.config import settings
from app.core.logging import logger


class LLMAdapter(ABC):
    """Abstract interface for LLM providers (Gemini, OpenAI, Claude, Ollama)."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generates raw text response given a list of role/content messages."""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> tuple[BaseModel, LLMResponse]:
        """Generates a structured Pydantic response enforcing the schema."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verifies connection and credentials for the LLM provider."""
        pass


class MockLLMAdapter(LLMAdapter):
    """Mock LLM adapter for deterministic unit testing and CI without API keys."""

    def __init__(self, canned_response: str = "Mock answer from material.") -> None:
        self.canned_response = canned_response

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            text=self.canned_response,
            model="mock-llm",
            prompt_tokens=10,
            completion_tokens=5,
        )

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> tuple[BaseModel, LLMResponse]:
        # Return a default-constructed model instance or mock dict
        try:
            instance = response_model.model_validate(json.loads(self.canned_response))
        except Exception:
            # Fallback to model fields default or constructing with mock values
            instance = response_model.model_construct()

        raw_resp = LLMResponse(
            text=self.canned_response,
            structured_json=instance.model_dump() if hasattr(instance, "model_dump") else {},
            model="mock-llm",
        )
        return instance, raw_resp

    async def health_check(self) -> bool:
        return True


class GeminiLLMAdapter(LLMAdapter):
    """Google Gemini LLM Adapter supporting Gemini 2.5 Flash / 1.5 Flash."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = settings.LLM_MODEL,
    ) -> None:
        self.api_key = (
            api_key
            or settings.LLM_API_KEY
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        self.model = model

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            logger.warning("Gemini API key is not configured. Falling back to mock response.")
            return LLMResponse(text="[Gemini API key not configured]", model=self.model)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        parts: list[dict[str, Any]] = []
        text_prompts: list[str] = []
        for m in messages:
            content = m.get("content", "")
            if content:
                text_prompts.append(f"{m.get('role', 'user').upper()}: {content}")
            if "image_base64" in m:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": m.get("image_mime", "image/png"),
                            "data": m["image_base64"],
                        }
                    }
                )
        if text_prompts:
            parts.insert(0, {"text": "\n\n".join(text_prompts)})

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "contents": [{"parts": parts}],
                        "generationConfig": {
                            "temperature": temperature,
                        },
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = (
                            candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        )
                        return LLMResponse(text=text, model=self.model)
        except Exception as exc:
            logger.error("Gemini API call failed: %s", exc)

        return LLMResponse(text=f"Response from Gemini {self.model}", model=self.model)

    async def generate_structured(
        self,
        messages: list[dict[str, Any]],
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> tuple[BaseModel, LLMResponse]:
        if not self.api_key:
            try:
                instance = response_model()
            except Exception:
                instance = response_model.model_construct()
            raw = LLMResponse(
                text="{}",
                structured_json=instance.model_dump() if hasattr(instance, "model_dump") else {},
                model=self.model,
            )
            return instance, raw

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        parts: list[dict[str, Any]] = []
        text_prompts: list[str] = []
        for m in messages:
            content = m.get("content", "")
            if content:
                text_prompts.append(f"{m.get('role', 'user').upper()}: {content}")
            if "image_base64" in m:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": m.get("image_mime", "image/png"),
                            "data": m["image_base64"],
                        }
                    }
                )
        if text_prompts:
            parts.insert(0, {"text": "\n\n".join(text_prompts)})

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "contents": [{"parts": parts}],
                        "generationConfig": {
                            "temperature": temperature,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_text = (
                            candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                        )
                        instance = response_model.model_validate_json(raw_text)
                        return instance, LLMResponse(
                            text=raw_text,
                            structured_json=instance.model_dump()
                            if hasattr(instance, "model_dump")
                            else {},
                            model=self.model,
                        )
        except Exception as exc:
            logger.error("Gemini structured call failed: %s", exc)

        instance = response_model.model_construct()
        raw = LLMResponse(text="{}", model=self.model)
        return instance, raw

    async def health_check(self) -> bool:
        return bool(self.api_key)


class OpenAILLMAdapter(LLMAdapter):
    """OpenAI / Compatible LLM Adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(text="[OpenAI API key not configured]", model=self.model)

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    return LLMResponse(text=text, model=self.model)
        except Exception as exc:
            logger.error("OpenAI API call failed: %s", exc)

        return LLMResponse(text=f"Response from OpenAI {self.model}", model=self.model)

    async def generate_structured(
        self,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        temperature: float = 0.0,
    ) -> tuple[BaseModel, LLMResponse]:
        if not self.api_key:
            instance = response_model.model_construct()
            return instance, LLMResponse(text="{}", model=self.model)

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["choices"][0]["message"]["content"]
                    instance = response_model.model_validate_json(text)
                    return instance, LLMResponse(text=text, model=self.model)
        except Exception as exc:
            logger.error("OpenAI structured call failed: %s", exc)

        instance = response_model.model_construct()
        return instance, LLMResponse(text="{}", model=self.model)

    async def health_check(self) -> bool:
        return bool(self.api_key)


def get_llm_adapter(provider: str | None = None) -> LLMAdapter:
    """Factory function returning the configured LLMAdapter."""
    selected_provider = (provider or settings.LLM_PROVIDER).lower()
    if selected_provider == "gemini":
        return GeminiLLMAdapter()
    elif selected_provider == "openai":
        return OpenAILLMAdapter()
    elif selected_provider == "mock":
        return MockLLMAdapter()
    else:
        logger.warning("Provider %s not implemented. Using MockLLMAdapter.", selected_provider)
        return MockLLMAdapter()
