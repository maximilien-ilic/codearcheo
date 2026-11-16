"""Run one agent task, or keep a conversation with streaming SDK message threads."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import BetaFunctionTool

from learn_it.agent.limits import AgentError, SessionLimitError, SessionLimits
from learn_it.agent.usage import UsageSummary
from learn_it.config import Settings

FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
BUDGET_BETA = "task-budgets-2026-03-13"
COMPACTION_BETA = "compact-2026-09-04"

ToolCallback = Callable[[str, dict[str, Any]], None]
TextCallback = Callable[[str], None]
UsageCallback = Callable[[UsageSummary], None]
Tool = Callable[..., str] | BetaFunctionTool


def _client() -> anthropic.Anthropic:
    client = anthropic.Anthropic()
    if not (client.api_key or client.auth_token or client.credentials):
        raise AgentError(
            "Aucun identifiant pour l'API Claude : exporte ANTHROPIC_API_KEY "
            "ou lance `ant auth login`."
        )
    return client


def _options(settings: Settings, *, conversation: bool = False) -> dict[str, Any]:
    options: dict[str, Any] = {}
    output: dict[str, Any] = {}
    betas = []
    if settings.effort:
        output["effort"] = settings.effort
    if settings.budget is not None:
        output["task_budget"] = {"type": "tokens", "total": settings.budget}
        betas.append(BUDGET_BETA)
    if output:
        options["output_config"] = output
    if settings.model in FALLBACK_MODELS:
        options["fallbacks"] = "default"
        betas.append(FALLBACK_BETA)
    if conversation:
        betas.append(COMPACTION_BETA)
    if betas:
        options["betas"] = betas
    return options


def _tools(tools: Sequence[Tool]) -> list[BetaFunctionTool]:
    return [tool if isinstance(tool, BetaFunctionTool) else beta_tool(tool) for tool in tools]


def _answer(message: Any, settings: Settings) -> str:
    if message is None:
        raise AgentError("Aucune réponse de Claude.")
    if message.stop_reason == "refusal":
        raise AgentError("Claude a refusé la demande (filtre de sécurité).")
    if message.stop_reason in {"tool_use", "pause_turn"}:
        raise AgentError(
            f"Arrêt après {settings.max_iterations} tours sans réponse finale : "
            "augmente LEARN_IT_MAX_ITERATIONS ou précise la demande."
        )
    answer = "\n".join(block.text for block in message.content if block.type == "text").strip()
    if not answer:
        raise AgentError("Claude n'a renvoyé aucun texte.")
    if message.stop_reason == "max_tokens":
        answer += "\n\n> Réponse tronquée : limite de longueur atteinte."
    return answer


def _consume(
    runner: Any,
    settings: Settings,
    on_tool: ToolCallback | None,
    on_text: TextCallback | None,
    on_usage: UsageCallback | None,
    *,
    compact: bool = False,
    limits: SessionLimits | None = None,
) -> str:
    started = time.monotonic()
    usage = UsageSummary()
    message = None
    prior_text = False
    try:
        for item in runner:
            if on_text is not None:
                streamed = False
                for event in item:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        if prior_text and not streamed:
                            on_text("\n\n")
                        on_text(event.delta.text)
                        streamed = True
                current = item.get_final_message()
                prior_text = prior_text or streamed
            else:
                current = item
            usage.add(current, settings.model)
            if limits is not None:
                limits.observe_response()
            if current.stop_reason != "compaction":
                message = current
            if on_tool:
                for block in current.content:
                    if block.type == "tool_use":
                        on_tool(block.name, block.input)
            if (
                compact
                and settings.compact_threshold
                and usage.last_context_tokens >= settings.compact_threshold
                and current.stop_reason == "end_turn"
            ):
                runner.compact_before_next_turn()
        answer = _answer(message, settings)
        if on_text and message.stop_reason == "max_tokens":
            on_text("\n\n> Réponse tronquée : limite de longueur atteinte.")
        return answer
    except SessionLimitError as exc:
        if limits is not None and limits.has_unobserved_attempts:
            usage.missing_usage = True
            usage.estimated_cost_usd = None
        if exc.compaction and message is not None and message.stop_reason == "end_turn":
            answer = _answer(message, settings)
            note = "\n\n> Compaction ignorée : limite locale de requêtes atteinte."
            if on_text:
                on_text(note)
            return answer + note
        raise
    except BaseException:
        # A failed or interrupted request may have billed tokens absent from the last usage.
        usage.missing_usage = True
        usage.estimated_cost_usd = None
        raise
    finally:
        if limits is not None and limits.has_unobserved_attempts:
            usage.missing_usage = True
            usage.estimated_cost_usd = None
        usage.elapsed_seconds = time.monotonic() - started
        try:
            if on_usage:
                on_usage(usage)
            else:
                print(usage.format(), file=sys.stderr)
        finally:
            close = getattr(runner, "close", None)
            if close:
                close()


def run_agent(
    system: str,
    task: str,
    tools: Sequence[Tool],
    settings: Settings,
    on_tool: ToolCallback | None = None,
    *,
    on_text: TextCallback | None = None,
    on_usage: UsageCallback | None = None,
    limits: SessionLimits | None = None,
) -> str:
    """Run one task; optionally stream text while retaining the final answer as a string."""
    if limits is None and (
        settings.max_requests is not None
        or settings.max_output_tokens != Settings.max_output_tokens
    ):
        limits = SessionLimits.from_settings(settings)
    if limits is not None:
        limits.ensure_available()
    client = _client()
    try:
        if limits is not None:
            client = client.with_middleware(limits.middleware)
        runner = client.beta.messages.tool_runner(
            model=settings.model,
            max_tokens=settings.max_output_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            cache_control={"type": "ephemeral"},
            messages=[{"role": "user", "content": task}],
            tools=_tools(tools),
            max_iterations=settings.max_iterations,
            **({"stream": True} if on_text is not None else {}),
            **_options(settings),
        )
        return _consume(runner, settings, on_tool, on_text, on_usage, limits=limits)
    finally:
        close = getattr(client, "close", None)
        if close:
            close()


class ConversationAgent:
    """One SDK thread across questions, including previous tool results and answers."""

    def __init__(
        self,
        system: str,
        tools: Sequence[Tool],
        settings: Settings,
        *,
        limits: SessionLimits | None = None,
    ) -> None:
        self.settings = settings
        self.limits = limits or (
            SessionLimits.from_settings(settings)
            if settings.max_requests is not None
            or settings.max_output_tokens != Settings.max_output_tokens
            else None
        )
        self.client = _client()
        if self.limits is not None:
            self.client = self.client.with_middleware(self.limits.middleware)
        self.thread = self.client.beta.messages.thread(
            model=settings.model,
            max_tokens=settings.max_output_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            cache_control={"type": "ephemeral"},
            messages=[],
            tools=_tools(tools),
            unsupported_request_behavior="continue_unthreaded",
            **_options(settings, conversation=True),
        )
        self.transcript: list[tuple[str, str]] = []

    def ask(
        self,
        question: str,
        *,
        on_tool: ToolCallback | None = None,
        on_text: TextCallback | None = None,
        on_usage: UsageCallback | None = None,
    ) -> str:
        if self.limits is not None:
            self.limits.ensure_available()
        self.thread.append({"role": "user", "content": question})
        try:
            runner = self.thread.tool_runner(
                max_iterations=self.settings.max_iterations, stream=on_text is not None
            )
            answer = _consume(
                runner, self.settings, on_tool, on_text, on_usage, compact=True, limits=self.limits
            )
        except SessionLimitError as exc:
            self.transcript += [
                ("Vous", question),
                ("Claude", f"> Réponse interrompue : {exc} Aucun résultat final n'a été produit."),
            ]
            raise
        self.transcript += [("Vous", question), ("Claude", answer)]
        return answer

    def markdown(self) -> str:
        return (
            "# Conversation learn-it\n\n"
            + "\n\n".join(f"## {role}\n\n{text}" for role, text in self.transcript)
            + "\n"
        )

    def close(self) -> None:
        self.client.close()
