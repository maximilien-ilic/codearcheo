"""The agent loop: Claude calls the project tools until it can answer.

The SDK's tool runner drives the loop (call the API, run the requested tools, send the
results back, repeat); this module configures it and checks how it ended.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import BetaFunctionTool

from learn_it.config import Settings

# On these models, a request declined by a safety classifier (possible on security-related
# code) is retried server-side on a fallback model instead of failing.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

ToolCallback = Callable[[str, dict[str, Any]], None]
Tool = Callable[..., str] | BetaFunctionTool


class AgentError(RuntimeError):
    """The agent stopped without a usable answer."""


def run_agent(
    system: str,
    task: str,
    tools: Sequence[Tool],
    settings: Settings,
    on_tool: ToolCallback | None = None,
) -> str:
    """Run the task to completion and return Claude's final answer (Markdown)."""
    options: dict[str, Any] = {}
    if settings.effort:
        options["output_config"] = {"effort": settings.effort}
    if settings.model in FALLBACK_MODELS:
        options |= {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    client = anthropic.Anthropic()  # resolves an API key, an auth token or an `ant` profile
    if not (client.api_key or client.auth_token or client.credentials):
        raise AgentError(
            "Aucun identifiant pour l'API Claude : exporte ANTHROPIC_API_KEY "
            "ou lance `ant auth login`."
        )

    runner = client.beta.messages.tool_runner(
        model=settings.model,
        max_tokens=16_000,
        # One breakpoint on the stable system prompt, plus automatic caching of the growing
        # conversation: every turn re-reads the previous ones from the cache.
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        cache_control={"type": "ephemeral"},
        messages=[{"role": "user", "content": task}],
        tools=[t if isinstance(t, BetaFunctionTool) else beta_tool(t) for t in tools],
        max_iterations=settings.max_iterations,
        **options,
    )

    message = None
    for message in runner:  # each reply is yielded before its tool calls run
        if on_tool:
            for block in message.content:
                if block.type == "tool_use":
                    on_tool(block.name, block.input)

    if message is None:
        raise AgentError("Aucune réponse de Claude.")
    if message.stop_reason == "refusal":
        raise AgentError("Claude a refusé la demande (filtre de sécurité).")
    if message.stop_reason == "tool_use":
        raise AgentError(
            f"Arrêt après {settings.max_iterations} tours sans réponse finale : "
            "augmente LEARN_IT_MAX_ITERATIONS ou précise la demande."
        )
    answer = "\n".join(b.text for b in message.content if b.type == "text").strip()
    if not answer:
        raise AgentError("Claude n'a renvoyé aucun texte.")
    if message.stop_reason == "max_tokens":
        answer += "\n\n> Réponse tronquée : limite de longueur atteinte."
    return answer
