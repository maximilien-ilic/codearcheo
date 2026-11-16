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
from rich.markup import escape

from learn_it import evidence, recommendations, render
from learn_it.agent import prompts
from learn_it.agent.runner import Tool, ToolCallback, run_agent
from learn_it.agent.tools import ProjectTools
from learn_it.config import Settings
from learn_it.domain import Decision, ProjectProfile, Recommendation
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

    def checked(self, answer: str) -> str:
        """Warn without hiding the answer; retain the same warning in saved reports."""
        report = evidence.verify(answer, self.project.root)
        render.err.print(escape(evidence.summary(report)))
        for citation, problem in report.problems.items():
            render.err.print(escape(f"  {citation.ref} : {problem}"))
        return f"{answer.rstrip()}\n\n{evidence.markdown_report(report)}\n"

    def run(self, task: str, extra_tools: Sequence[Tool] = (), *, check: bool = True) -> str:
        tools = ProjectTools(self.project.root).exploration()
        system = prompts.SYSTEM.format(profile=self.profile.model_dump_json(indent=1))
        answer = run_agent(system, task, [*tools, *extra_tools], self.settings, self.on_tool)
        return self.checked(answer) if check else answer


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
    synthesis = session.run(
        prompts.DECISIONS.format(language=session.settings.language), [tool], check=False
    )
    session.store.save_decisions(
        recorded, head=session.profile.head if not session.profile.uncommitted else None
    )
    report = session.checked(render.decisions_markdown(recorded, synthesis))
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
    recorded: list[Recommendation] = []

    def record_recommendation(**fields: Any) -> str:
        """Record one evidence-based recommendation about a technical decision."""
        try:
            recorded.append(Recommendation.model_validate(fields))
        except ValidationError as exc:
            raise ToolError(f"Invalid recommendation, fix it and call again:\n{exc}") from exc
        return f"Recorded recommendation {len(recorded)}: {recorded[-1].title}"

    tool = beta_tool(record_recommendation, input_schema=Recommendation)
    task = prompts.REVIEW.format(known_decisions=known_block, language=session.settings.language)
    task += (
        "\nRecord each recommendation with record_recommendation, including keep verdicts. "
        "Use keep/improve/replace, low/medium/high impact, S/M/L effort. Give reasons, proposal, "
        "tradeoffs, first_steps and evidence. Then return a concise synthesis."
    )
    synthesis = session.run(task, [tool], check=False)
    recorded = recommendations.ordered(recorded)
    session.store.save_recommendations(recorded)
    report = session.checked(recommendations.markdown(recorded, synthesis))
    session.store.save_report("review", report)
    return report
