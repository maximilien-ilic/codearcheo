"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "learn-it"


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    # low | medium | high | xhigh | max. Empty to omit it, for models without effort support.
    effort: str = "high"
    language: str = "French"  # language of generated reports; `ask` answers in the question's
    max_iterations: int = 40  # agent round-trips before giving up
    cache_dir: Path = field(default_factory=_default_cache_dir)  # where GitHub repos are cloned

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ.get
        return cls(
            model=env("LEARN_IT_MODEL", cls.model),
            effort=env("LEARN_IT_EFFORT", cls.effort),
            language=env("LEARN_IT_LANG", cls.language),
            max_iterations=int(env("LEARN_IT_MAX_ITERATIONS", cls.max_iterations)),
            cache_dir=Path(env("LEARN_IT_CACHE_DIR", _default_cache_dir())),
        )
