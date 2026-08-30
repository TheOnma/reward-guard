"""Thin, provider-agnostic LLM wrapper. Swap providers via env (JUDGE_PROVIDER)."""
from __future__ import annotations

from .config import settings


class LLM:
    """Minimal chat wrapper over Anthropic or OpenAI. One method: complete()."""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or settings.judge_provider).lower()
        self.model = model or settings.judge_model
        self._client = None

    def _anthropic(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _openai(self):
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=settings.openai_api_key)
        return self._client

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """Return the model's text response."""
        if self.provider == "anthropic":
            resp = self._anthropic().messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        elif self.provider == "openai":
            resp = self._openai().chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content or ""
        raise ValueError(f"Unknown provider: {self.provider}")
