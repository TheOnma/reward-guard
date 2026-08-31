"""Thin, provider-agnostic LLM wrapper. Swap providers via env (JUDGE_PROVIDER).

Determinism note: every judge/verifier call requests greedy decoding where the provider
still exposes it -- `temperature=0` (and a fixed `seed` on OpenAI). Current Anthropic
models (Sonnet 5 / Opus 5 / 4.6+) removed the sampling parameters from the SDK surface, so
`temperature` cannot be pinned there; residual run-to-run variance is instead *measured*
with `python -m evals.run_eval --runs N` (mean + min/max per metric).
"""
from __future__ import annotations

import inspect
import socket
import threading

from .config import settings

# Fixed seed for providers that accept one (OpenAI). Arbitrary but constant.
SEED = 20250815


def _install_dns_overrides(spec: str) -> None:
    """Opt-in only: patch socket.getaddrinfo for hosts a broken local resolver can't resolve.

    `spec` is "host=ip,host=ip". No-op when empty (the normal case). TLS still verifies the
    real hostname (SNI is unchanged) -- only address lookup is redirected.
    """
    mapping = {}
    for pair in spec.split(","):
        if "=" in pair:
            host, ip = pair.split("=", 1)
            mapping[host.strip()] = ip.strip()
    if not mapping:
        return
    _orig = socket.getaddrinfo
    if getattr(_orig, "_rg_patched", False):
        return
    def patched(host, *args, **kwargs):
        return _orig(mapping.get(host, host), *args, **kwargs)
    patched._rg_patched = True
    socket.getaddrinfo = patched


_install_dns_overrides(settings.dns_override)


class _Usage:
    """Process-wide tally of judge/verifier LLM calls (for the repro guide's cost line)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = self.input_tokens = self.output_tokens = 0

    def add(self, in_tok: int, out_tok: int) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += in_tok
            self.output_tokens += out_tok

    def reset(self) -> None:
        with self._lock:
            self.calls = self.input_tokens = self.output_tokens = 0

    def as_dict(self) -> dict:
        return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


USAGE = _Usage()


def _accepts(fn, param: str) -> bool:
    """True if `fn`'s signature explicitly names `param` (so passing it won't TypeError)."""
    try:
        return param in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


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
        """Return the model's text response (greedy decoding where the provider allows it)."""
        if self.provider == "anthropic":
            create = self._anthropic().messages.create
            kwargs = dict(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if _accepts(create, "temperature"):  # older models only; removed on Sonnet 5+
                kwargs["temperature"] = 0
            resp = create(**kwargs)
            u = getattr(resp, "usage", None)
            if u is not None:
                USAGE.add(getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

        elif self.provider == "openai":
            create = self._openai().chat.completions.create
            kwargs = dict(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,
                seed=SEED,
            )
            try:
                resp = create(**kwargs)
            except TypeError:  # SDK too old for seed, or model rejects sampling params
                kwargs.pop("seed", None)
                kwargs.pop("temperature", None)
                resp = create(**kwargs)
            u = getattr(resp, "usage", None)
            if u is not None:
                USAGE.add(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)
            return resp.choices[0].message.content or ""

        raise ValueError(f"Unknown provider: {self.provider}")
