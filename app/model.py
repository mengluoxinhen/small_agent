"""Turn `Settings` into an Agents-SDK `Model`.

Building a model must be free of network I/O: FastAPI constructs it at startup and tests
construct it thousands of times, so no request may happen here.
"""

from __future__ import annotations

from agents.models.interface import Model
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from app.config import Settings
from app.testing.fake_model import FakeModel


def build_openai_client(settings: Settings) -> AsyncOpenAI:
    """Client for any OpenAI-compatible endpoint (DeepSeek, DashScope, vLLM, ...)."""
    return AsyncOpenAI(
        api_key=settings.require_api_key(),
        base_url=settings.llm_base_url,
    )


def build_model(settings: Settings) -> Model:
    """The single place that decides which model the agent talks to."""
    if settings.model_backend == "fake":
        return FakeModel()
    return OpenAIChatCompletionsModel(
        model=settings.llm_model,
        openai_client=build_openai_client(settings),
    )
