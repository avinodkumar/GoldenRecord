"""LLM client interface for the agents.

In the solution the LLM is Fabric AI Functions (fabric_runtime.FabricAIFunctionsLLM): no keys, no
external endpoint. Outside Fabric, the offline dev harness picks a backend with LLM_PROVIDER:
  none          no LLM; agents use their deterministic fallbacks (default)
  azure_openai  Azure OpenAI deployment, the same model family Fabric AI Functions use
                (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT)

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


class AzureOpenAILLM(LLMClient):
    """Dev-harness backend: Azure OpenAI chat completions with a strict JSON schema."""
    provider = "azure_openai"

    def __init__(self):
        super().__init__()
        from openai import AzureOpenAI

        self.client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
        self.model = os.environ["AZURE_OPENAI_DEPLOYMENT"]

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
        if provider == "azure_openai":
            return AzureOpenAILLM()
    except Exception as exc:
        log.warning("LLM provider %s unavailable, running rules-only: %s", provider, exc)
        return None
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")
