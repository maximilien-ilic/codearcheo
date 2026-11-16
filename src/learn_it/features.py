"""Use cases. Each one is a task prompt that the agent runs over the project's tools.

Adding a feature: a prompt in `agent/prompts.py`, a function here, a command in `cli.py`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from anthropic import beta_tool
from anthropic.lib.tools import ToolError
from pydantic import ValidationError

from learn_it import render
from learn_it.agent import prompts
from learn_it.agent.runner import Tool, ToolCallback, run_agent
from learn_it.agent.tools import ProjectTools
from learn_it.config import Settings
from learn_it.domain import Decision, ProjectProfile
from learn_it.sources import Project
from learn_it.store import Store


@dataclass
class Session:
    """A project ready to be questioned: on disk, profiled, with its store and settings."""

    project: Project
    profile: ProjectProfile
    store: Store
    settings: Settings
    on_tool: ToolCallback | None = None

    def run(self, task: str, extra_tools: Sequence[Tool] = ()) -> str:
        tools = ProjectTools(self.project.root, self.profile).exploration()
        system = prompts.SYSTEM.format(profile=self.profile.model_dump_json(indent=1))
        return run_agent(system, task, [*tools, *extra_tools], self.settings, self.on_tool)


def ask(session: Session, question: str) -> str:
    return session.run(prompts.ASK.format(question=question))


def overview(session: Session) -> str:
    report = session.run(prompts.OVERVIEW.format(language=session.settings.language))
    session.store.save_report("overview", report)
    return report


def why(session: Session, target: str) -> str:
    return session.run(prompts.WHY.format(target=target, language=session.settings.language))


def decisions(session: Session) -> str:
    """Reconstruct the project's decisions as structured records, saved as JSON and Markdown."""
    recorded: list[Decision] = []

    def record_decision(**fields: Any) -> str:
        """Record one technical decision of the project as an architecture decision record."""
        try:
            recorded.append(Decision.model_validate(fields))
        except ValidationError as exc:
            raise ToolError(f"Invalid record, fix it and call again:\n{exc}") from exc
        return f"Recorded decision {len(recorded)}: {recorded[-1].title}"

    tool = beta_tool(record_decision, input_schema=Decision)
    synthesis = session.run(prompts.DECISIONS.format(language=session.settings.language), [tool])
    session.store.save_decisions(recorded)
    report = render.decisions_markdown(recorded, synthesis)
    session.store.save_report("decisions", report)
    return report


def review(session: Session) -> str:
    known = session.store.load_decisions()
    known_block = (
        prompts.KNOWN_DECISIONS.format(
            decisions=json.dumps([d.model_dump() for d in known], ensure_ascii=False, indent=1)
        )
        if known
        else ""
    )
    report = session.run(
        prompts.REVIEW.format(known_decisions=known_block, language=session.settings.language)
    )
    session.store.save_report("review", report)
    return report
