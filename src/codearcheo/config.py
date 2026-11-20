"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "codearcheo"


def getenv(name: str, default: str | None = None) -> str | None:
    """`CODEARCHEO_<name>`, else the variable from before the rename (`LEARN_IT_<name>`)."""
    value = os.environ.get(f"CODEARCHEO_{name}")
    if value is None:
        value = os.environ.get(f"LEARN_IT_{name}")
    return default if value is None else value


def cache_dir_from_env() -> Path:
    return Path(getenv("CACHE_DIR") or _default_cache_dir())


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    # low | medium | high | xhigh | max. Empty to omit it, for models without effort support.
    effort: str = "medium"
    language: str = "French"  # language of generated reports; `ask` answers in the question's
    max_iterations: int = 40  # agent round-trips before giving up
    cache_dir: Path = field(default_factory=_default_cache_dir)  # where GitHub repos are cloned
    budget: int | None = None  # advisory API task budget in tokens, not dollars
    compact_threshold: int = 100_000  # context tokens; 0 disables automatic compaction
    max_requests: int | None = None  # local HTTP attempt limit, shared across the session
    max_output_tokens: int = 16_000  # enforced max_tokens for each generation request
    # "api": Anthropic API credits. "claude-code": `claude -p`, on the Claude subscription.
    backend: str = "api"

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Le modèle ne peut pas être vide.")
        if self.max_iterations < 1:
            raise ValueError("CODEARCHEO_MAX_ITERATIONS doit être positif.")
        if self.budget is not None and self.budget < 20_000:
            raise ValueError("Le budget de tâche doit être d'au moins 20 000 tokens.")
        if self.effort not in {"", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Effort attendu : low, medium, high, xhigh, max, ou vide.")
        if self.compact_threshold < 0:
            raise ValueError("CODEARCHEO_COMPACT_THRESHOLD ne peut pas être négatif.")
        if self.max_requests is not None and (
            type(self.max_requests) is not int or self.max_requests < 1
        ):
            raise ValueError("La limite de requêtes doit être un entier positif.")
        if self.backend not in {"api", "claude-code"}:
            raise ValueError("CODEARCHEO_BACKEND attendu : api ou claude-code.")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("La limite de tokens de sortie doit être un entier positif.")

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        effort: str | None = None,
        budget: int | None = None,
        max_requests: int | None = None,
        max_output_tokens: int | None = None,
        backend: str | None = None,
    ) -> Settings:
        env = getenv
        selected_backend = backend if backend is not None else env("BACKEND", cls.backend)
        output_limit = env("MAX_OUTPUT_TOKENS")
        if selected_backend == "claude-code" and (
            max_output_tokens is not None or output_limit is not None
        ):
            raise ValueError("--max-output-tokens ne s'applique pas au moteur claude-code.")
        return cls(
            model=model if model is not None else env("MODEL", cls.model),
            effort=effort if effort is not None else env("EFFORT", cls.effort),
            language=env("LANG", cls.language),
            max_iterations=int(env("MAX_ITERATIONS", cls.max_iterations)),
            cache_dir=cache_dir_from_env(),
            budget=budget
            if budget is not None
            else (int(env("BUDGET")) if env("BUDGET") else None),
            compact_threshold=int(env("COMPACT_THRESHOLD", cls.compact_threshold)),
            max_requests=max_requests
            if max_requests is not None
            else (int(env("MAX_REQUESTS")) if env("MAX_REQUESTS") else None),
            max_output_tokens=max_output_tokens
            if max_output_tokens is not None
            else int(env("MAX_OUTPUT_TOKENS", cls.max_output_tokens)),
            backend=selected_backend,
        )
