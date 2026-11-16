"""Measured API usage and a conservative estimate at public standard Claude API rates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# USD / million tokens: input, output, 5m writes, 1h writes, reads. Verified 2026-11-16:
# https://platform.claude.com/docs/en/about-claude/pricing
# Unknown models and nonstandard service modes deliberately have no estimated price.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 5.0, 8.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 10.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 2.50, 4.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 2.50, 4.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 12.50, 20.0, 0.25),
}


def _value(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


@dataclass
class UsageSummary:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    requests: int = 0
    tool_calls: int = 0
    elapsed_seconds: float = 0.0
    estimated_cost_usd: float | None = 0.0
    missing_usage: bool = False
    last_context_tokens: int = 0

    def add(self, message: Any, default_model: str) -> None:
        self.requests += 1
        self.tool_calls += sum(block.type == "tool_use" for block in message.content)
        usage = getattr(message, "usage", None)
        if usage is None:
            self.missing_usage = True
            self.estimated_cost_usd = None
            return
        model = getattr(message, "model", default_model)
        self._add_usage(usage, model)
        # Compaction iterations are billed separately, outside the top-level totals.
        for item in _value(usage, "iterations", []) or []:
            if _value(item, "type") == "compaction":
                self._add_usage(item, model, update_context=False)

    def _add_usage(self, usage: Any, model: str, *, update_context: bool = True) -> None:
        inputs = _value(usage, "input_tokens", 0) or 0
        outputs = _value(usage, "output_tokens", 0) or 0
        writes = _value(usage, "cache_creation_input_tokens", 0) or 0
        reads = _value(usage, "cache_read_input_tokens", 0) or 0
        self.input_tokens += inputs
        self.output_tokens += outputs
        self.cache_creation_input_tokens += writes
        self.cache_read_input_tokens += reads
        if update_context:
            self.last_context_tokens = inputs + writes + reads + outputs
        rates = PRICES.get(model)
        nonstandard = (
            _value(usage, "speed") not in (None, "standard")
            or _value(usage, "service_tier") not in (None, "standard")
            or _value(usage, "inference_geo") not in (None, "global")
        )
        if rates is None or nonstandard:
            self.estimated_cost_usd = None
        if self.estimated_cost_usd is not None and rates is not None:
            cache = _value(usage, "cache_creation")
            one_hour = _value(cache, "ephemeral_1h_input_tokens", 0) or 0
            if not 0 <= one_hour <= writes:
                self.estimated_cost_usd = None
                return
            counts = (inputs, outputs, writes - one_hour, one_hour, reads)
            self.estimated_cost_usd += (
                sum(n * price for n, price in zip(counts, rates, strict=True)) / 1e6
            )

    @property
    def cache_share(self) -> float:
        total = self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens
        return self.cache_read_input_tokens / total if total else 0.0

    def format(self) -> str:
        cost = (
            f"${self.estimated_cost_usd:.6f} estimé (tarifs standard 2026-11-16)"
            if self.estimated_cost_usd is not None and self.requests
            else "coût indisponible"
        )
        suffix = " · usage partiel/indisponible" if self.missing_usage else ""
        return (
            f"Usage : entrée {self.input_tokens} · sortie {self.output_tokens} · "
            f"cache écrit {self.cache_creation_input_tokens}, lu {self.cache_read_input_tokens} "
            f"({self.cache_share:.0%} des entrées) · {self.requests} requête(s), "
            f"{self.tool_calls} appel(s) d'outils · {self.elapsed_seconds:.2f} s · {cost}{suffix}"
        )
