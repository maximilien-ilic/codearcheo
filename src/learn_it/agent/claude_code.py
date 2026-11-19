"""Run an agent task through Claude Code's headless mode (`claude -p`), so that it runs on
the user's Claude subscription instead of API credits.

Claude Code gets learn-it's own system prompt in place of its default one, none of its
built-in tools, and learn-it's read-only tools through `learn-it serve` (MCP): the same
tools, prompts and project profile as the API runner. Recording tools (`record_decision`,
`record_recommendation`) live in this process and cannot cross the MCP boundary, so their
records come back as structured output and are replayed here through the same validation.

What differs from the API runner: no streaming, no local request limits, an uncapped
output for the citation repair request, and the reported cost is an API-equivalent figure,
not what the subscription bills.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from anthropic.lib.tools import BetaFunctionTool, ToolError

from learn_it.agent.limits import AgentError
from learn_it.agent.usage import UsageSummary
from learn_it.config import Settings

SERVER = "learn-it"
TIMEOUT_SECONDS = 30 * 60
# Without them, Claude Code falls back to the subscription the user is logged in with.
_API_CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _schema(tools: Sequence[BetaFunctionTool]) -> dict[str, Any]:
    """Structured output carrying the synthesis and, per recording tool, its records."""
    properties: dict[str, Any] = {"synthesis": {"type": "string"}}
    definitions: dict[str, Any] = {}
    for tool in tools:
        items = copy.deepcopy(tool.input_schema)
        definitions.update(items.pop("$defs", {}))
        properties[tool.name] = {"type": "array", "items": items}
    schema = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if definitions:
        schema["$defs"] = definitions
    return schema


def _usage(result: dict[str, Any], elapsed: float) -> UsageSummary:
    usage = result.get("usage") or {}
    return UsageSummary(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        requests=result.get("num_turns", 0),
        elapsed_seconds=elapsed,
        estimated_cost_usd=result.get("total_cost_usd"),
        missing_usage=not usage,
    )


def run_claude_code(
    system: str,
    task: str,
    tools: Sequence[BetaFunctionTool],
    settings: Settings,
    *,
    root: Path,
    on_usage: Any = None,
    exploration: bool = True,
) -> str:
    """Run one task with `claude -p`. `tools` are only the recording tools: the exploration
    tools come from `learn-it serve`, unless `exploration` is off (a tool-free request)."""
    executable = shutil.which("claude")
    if executable is None:
        raise AgentError(
            "Claude Code est introuvable : installe-le ou utilise LEARN_IT_BACKEND=api."
        )
    if settings.max_requests is not None:
        raise AgentError("--max-requests ne s'applique pas au moteur claude-code.")
    if settings.max_output_tokens != Settings.max_output_tokens:
        raise AgentError("--max-output-tokens ne s'applique pas au moteur claude-code.")
    if exploration and find_spec("mcp") is None:
        raise AgentError(
            "Le moteur claude-code exige l'extra mcp : uv tool install --editable '.[mcp]'"
        )

    prompt, schema = task, None
    if tools:
        names = [tool.name for tool in tools]
        schema = _schema(tools)
        prompt += (
            f"\n\nThe tools {', '.join(names)} are not available here. Put each record you "
            "would have passed to them in the array of the same name in your structured "
            "output, and your final synthesis in `synthesis`. Only the structured output is "
            "kept: do not write the answer as text first."
        )

    with tempfile.TemporaryDirectory(prefix="learn-it-claude-") as scratch:
        config = Path(scratch) / "mcp.json"
        servers = {SERVER: {
            "command": sys.executable,
            "args": ["-m", "learn_it", "serve", "-p", str(root)],
        }} if exploration else {}
        config.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        command = [
            executable, "-p", prompt, "--output-format", "json",
            "--system-prompt", system,
            "--tools", "", "--strict-mcp-config", "--mcp-config", str(config),
            "--setting-sources", "",
            "--no-session-persistence", "--model", settings.model,
            "--max-turns", str(settings.max_iterations),
        ]
        if exploration:
            command += ["--allowedTools", f"mcp__{SERVER}"]
        if settings.effort:
            command += ["--effort", settings.effort]
        if schema is not None:
            command += ["--json-schema", json.dumps(schema)]
        env = {key: value for key, value in os.environ.items() if key not in _API_CREDENTIALS}
        # `learn-it serve` scans the project before answering: the first scan of a very large
        # repository can outlast Claude Code's default MCP startup timeout.
        env.setdefault("MCP_TIMEOUT", "180000")
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command, cwd=root, env=env, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentError("Claude Code n'a pas répondu dans le temps imparti.") from exc

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = (proc.stderr or proc.stdout).strip()[-500:]
        raise AgentError(f"Claude Code a échoué (code {proc.returncode}) : {detail}") from None
    usage = _usage(result, time.monotonic() - started)
    if on_usage is not None:
        on_usage(usage)
    else:
        print(usage.format(), file=sys.stderr)
    if result.get("subtype") == "error_max_turns":
        raise AgentError(
            f"Claude Code arrêté après {settings.max_iterations} tours sans réponse finale : "
            "augmente LEARN_IT_MAX_ITERATIONS ou précise la demande."
        )
    if proc.returncode != 0 or result.get("is_error"):
        raise AgentError(f"Claude Code a échoué : {str(result.get('result', ''))[:500]}")

    if schema is None:
        answer = str(result.get("result") or "").strip()
        if not answer:
            raise AgentError("Claude Code n'a renvoyé aucun texte.")
        return answer

    output = result.get("structured_output") or {}
    rejected = 0
    for tool in tools:
        for record in output.get(tool.name) or []:
            try:
                tool.call(record)
            except (ToolError, ValueError, TypeError):
                rejected += 1
    if rejected:
        print(f"Claude Code : {rejected} enregistrement(s) invalide(s) ignoré(s).", file=sys.stderr)
    return str(output.get("synthesis") or "").strip()
