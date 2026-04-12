"""
llm_provider.py — Abstração de LLM · Agente HSE-IT · Vivamente 360°
──────────────────────────────────────────────────────────────────────
Implementa o padrão Strategy para troca de provider sem alterar o core.

Variáveis de ambiente por provider:
    LLM_PROVIDER = openrouter | openai | anthropic   (padrão: openrouter)

    # OpenRouter
    OPENROUTER_API_KEY = "sk-or-..."
    OPENROUTER_MODEL   = "meta-llama/llama-3.3-70b-instruct"  (opcional)

    # OpenAI
    OPENAI_API_KEY = "sk-..."
    OPENAI_MODEL   = "gpt-4o"  (opcional)

    # Anthropic
    ANTHROPIC_API_KEY = "sk-ant-..."
    ANTHROPIC_MODEL   = "claude-sonnet-4-5"  (opcional)
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════
# INTERFACE — contrato que todos os providers devem cumprir
# ════════════════════════════════════════════════════════════

class LLMProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        """Envia system + user e retorna resposta como dict Python."""
        ...


# ════════════════════════════════════════════════════════════
# HELPER — limpeza de markdown fence residual
# ════════════════════════════════════════════════════════════

def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return text.strip()


# ════════════════════════════════════════════════════════════
# PROVIDER: OpenRouter  (padrão atual)
# ════════════════════════════════════════════════════════════

class OpenRouterProvider(LLMProvider):
    _DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"
    _BASE_URL      = "https://openrouter.ai/api/v1"

    def __init__(self) -> None:
        import openai  # openai SDK ≥ 1.x é compatível com OpenRouter
        api_key = os.environ["OPENROUTER_API_KEY"]
        self._client = openai.OpenAI(api_key=api_key, base_url=self._BASE_URL)
        self._model  = os.environ.get("OPENROUTER_MODEL", self._DEFAULT_MODEL)

    @property
    def model_name(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        raw = resp.choices[0].message.content
        return json.loads(_strip_fence(raw))


# ════════════════════════════════════════════════════════════
# PROVIDER: OpenAI
# ════════════════════════════════════════════════════════════

class OpenAIProvider(LLMProvider):
    _DEFAULT_MODEL = "gpt-4o"

    def __init__(self) -> None:
        import openai
        self._client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model  = os.environ.get("OPENAI_MODEL", self._DEFAULT_MODEL)

    @property
    def model_name(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        raw = resp.choices[0].message.content
        return json.loads(_strip_fence(raw))


# ════════════════════════════════════════════════════════════
# PROVIDER: Anthropic
# ════════════════════════════════════════════════════════════

class AnthropicProvider(LLMProvider):
    _DEFAULT_MODEL = "claude-sonnet-4-5"

    def __init__(self) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._model  = os.environ.get("ANTHROPIC_MODEL", self._DEFAULT_MODEL)

    @property
    def model_name(self) -> str:
        return self._model

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        # Anthropic não tem response_format=json_object nativo;
        # injetamos instrução no system prompt para garantir JSON puro.
        system_with_json = (
            system
            + "\n\nIMPORTANTE: retorne APENAS o objeto JSON, sem texto antes ou depois."
        )
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=0.3,
            system=system_with_json,
            messages=[{"role": "user", "content": user}],
        )
        raw = msg.content[0].text
        return json.loads(_strip_fence(raw))


# ════════════════════════════════════════════════════════════
# FACTORY — resolve provider via LLM_PROVIDER env var
# ════════════════════════════════════════════════════════════

_REGISTRY: dict[str, type[LLMProvider]] = {
    "openrouter": OpenRouterProvider,
    "openai":     OpenAIProvider,
    "anthropic":  AnthropicProvider,
}

_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _instance
    if _instance is None:
        name = os.environ.get("LLM_PROVIDER", "openrouter").lower()
        cls  = _REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"LLM_PROVIDER='{name}' inválido. Opções: {list(_REGISTRY)}"
            )
        _instance = cls()
        log.info("LLM provider: %s | modelo: %s", name, _instance.model_name)
    return _instance