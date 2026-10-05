"""Pluggable LLM client for the agents (a stand-in for Fabric AI Functions).

LLM_PROVIDER selects the backend:
  none          no LLM; agents use their deterministic fallbacks (default, works offline)
  anthropic     Claude via the Anthropic SDK (ANTHROPIC_API_KEY)
  azure_openai  Azure OpenAI deployment (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT)
  ollama        local model through Ollama's OpenAI-compatible endpoint (OLLAMA_BASE_URL, OLLAMA_MODEL)

Every call returns parsed JSON that matches the given JSON schema, or None on any failure, so a
broken or missing LLM degrades the agents to rules-only instead of stopping the pipeline.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class LLMStats:
    calls: int = 0
    failures: int = 0
    budget: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_CALLS_PER_RUN", "50")))

    @property
    def exhausted(self) -> bool:
        return self.calls >= self.budget


class LLMClient:
    provider = "none"
    model = ""

    def __init__(self):
        self.stats = LLMStats()

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict | None:
        if self.stats.exhausted:
            return None
        self.stats.calls += 1
        try:
            return self._complete_json(system, prompt, schema)
        except Exception as exc:  # any provider error falls back to rules-only behaviour
            self.stats.failures += 1
            log.warning("LLM call failed (%s): %s", self.provider, exc)
            return None

    def _complete_json(self, system: str, prompt: str, schema: dict) -> dict | None:
        raise NotImplementedError


class AnthropicLLM(LLMClient):
    provider = "anthropic"

    def __init__(self):
        super().__init__()
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = os.environ.get("LLM_MODEL", "claude-opus-5-5")

    def _complete_json(self, system, prompt, schema):
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            # Server-side fallback: if the model declines, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        return json.loads(text) if text else None


class OpenAICompatibleLLM(LLMClient):
    """Azure OpenAI or Ollama, both through the openai SDK's chat completions API."""

    def __init__(self, provider: str):
        super().__init__()
        self.provider = provider
        if provider == "azure_openai":
            from openai import AzureOpenAI

            self.client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            )
            self.model = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        else:
            from openai import OpenAI

            self.client = OpenAI(base_url=os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434/v1"),
                                 api_key="ollama")
            self.model = os.environ.get("OLLAMA_MODEL", "llama3.2")

    def _complete_json(self, system, prompt, schema):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "result", "schema": schema, "strict": True}},
        )
        content = response.choices[0].message.content
        return json.loads(content) if content else None


def get_llm() -> LLMClient | None:
    provider = os.environ.get("LLM_PROVIDER", "none").strip().lower()
    if provider in ("", "none"):
        return None
    try:
        if provider == "anthropic":
            return AnthropicLLM()
        if provider in ("azure_openai", "ollama"):
            return OpenAICompatibleLLM(provider)
    except Exception as exc:
        log.warning("LLM provider %s unavailable, running rules-only: %s", provider, exc)
        return None
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
