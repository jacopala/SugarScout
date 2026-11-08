"""Thin model gateway (Section 5.1): one place that talks to the NVIDIA API catalog.

The catalog is OpenAI-compatible, so models are swapped by configuration only.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from openai import AsyncOpenAI

from sugarscout.settings import Settings

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class ChatModel(Protocol):
    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str: ...


class LlmUnavailable(RuntimeError):
    pass


class NvidiaGateway:
    def __init__(self, settings: Settings) -> None:
        if not settings.llm_configured:
            raise LlmUnavailable("NVIDIA_API_KEY is not set")
        self._client = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=1,
        )

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict[str, object] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # Typed as Any: the SDK's overloads only know OpenAI's own model names.
        create: Any = self._client.chat.completions.create
        resp = await create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        content = resp.choices[0].message.content or ""
        # Reasoning models may inline their thinking; the child must never see it.
        return _THINK.sub("", content).strip()


def get_gateway(settings: Settings) -> ChatModel | None:
    try:
        return NvidiaGateway(settings)
    except LlmUnavailable:
        return None
