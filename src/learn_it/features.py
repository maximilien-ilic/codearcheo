"""Use cases. Each one is a task prompt that the agent runs over the project's tools.

Adding a feature: a prompt in `agent/prompts.py`, a function here, a command in `cli.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from anthropic import beta_tool
from anthropic.lib.tools import ToolError
from pydantic import ValidationError
from rich.markup import escape

from learn_it import evidence, recommendations, render
from learn_it.agent import prompts
from learn_it.agent.runner import (
    AgentError,
    TextCallback,
    Tool,
    ToolCallback,
    UsageCallback,
    run_agent,
)
from learn_it.agent.tools import ProjectTools
from learn_it.analyzers import adrs, code
from learn_it.citation_repair import RepairResult, repair_answer
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
    on_text: TextCallback | None = None
    on_usage: UsageCallback | None = None
    repair_citations: bool = False
    _last_repair: RepairResult | None = field(default=None, init=False, repr=False)

    @property
    def last_repair(self) -> dict[str, Any] | None:
        """A fresh view of immutable initial/final evidence metadata for offline comparisons."""
        return self._last_repair.as_dict() if self._last_repair is not None else None

    def checked(self, answer: str, *, repair: bool = False) -> str:
        """Warn without hiding the answer; retain the same warning in saved reports."""
        report = evidence.verify(answer, self.project.root)
        repair_note = ""
        if repair and self.repair_citations:
            options: dict[str, Any] = {}
            if self.on_usage is not None:
                options["on_usage"] = self.on_usage
            # The shared session limiter is supplied by the CLI/session integration.
            limits = getattr(self, "limits", None)
            if limits is not None:
                options["limits"] = limits
            self._last_repair = repair_answer(
                answer, self.project.root, self.settings, initial=report,
                commits=[{"sha": c.sha, "subject": c.subject} for c in self.profile.recent_commits],
                call_options=options,
            )
            answer = self._last_repair.selected_answer
            report = self._last_repair.selected_report.report()
            if self._last_repair.attempted:
                repair_note = f"\n\n{self._last_repair.markdown()}"
        render.err.print(escape(evidence.summary(report)))
        for citation, problem in report.problems.items():
            render.err.print(escape(f"  {citation.ref} : {problem}"))
        return f"{answer.rstrip()}\n\n{evidence.markdown_report(report)}{repair_note}\n"

    def run(
        self, task: str, extra_tools: Sequence[Tool] = (), *, check: bool = True,
        buffer_text: bool = False,
    ) -> str:
        self._last_repair = None
        tools = ProjectTools(self.project.root).exploration()
        system = prompts.SYSTEM.format(profile=self.profile.model_dump_json(indent=1))
        repair = self.repair_citations and check and not extra_tools
        buffered = buffer_text or repair
        options = {"on_text": self.on_text} if self.on_text is not None and not buffered else {}
        if self.on_usage is not None:
            options["on_usage"] = self.on_usage
        answer = run_agent(
            system, task, [*tools, *extra_tools], self.settings, self.on_tool, **options
        )
        if not check:
            return answer
        checked = self.checked(answer, repair=repair)
        if self.on_text is not None:
            self.on_text(checked if buffered else checked[len(answer.rstrip()):])
        return checked


def ask(session: Session, question: str) -> str:
    return session.run(prompts.ASK.format(question=question))


def overview(session: Session) -> str:
    graph = code.analyze(session.project.root)
    task = prompts.OVERVIEW.format(language=session.settings.language)
    diagram = graph.mermaid() if graph is not None else None
    if diagram:
        task += (
            "\nThis diagram is computed from actual static imports. Use this exact diagram "
            "and explain it; do not invent edges. Unresolved, external and dynamic imports "
            "are not edges.\n<actual_imports>\n" + diagram + "\n</actual_imports>"
        )
    report = session.run(task, check=False, buffer_text=session.repair_citations)
    if diagram:
        fence = f"```mermaid\n{diagram}\n```"
        pattern = re.compile(r"```mermaid[^\n]*\n.*?```", re.DOTALL | re.IGNORECASE)
        if match := pattern.search(report):
            report = report[:match.start()] + fence + pattern.sub("", report[match.end():])
        else:
            report += f"\n\n## Imports statiques observés\n\n{fence}"
    report = session.checked(report, repair=session.repair_citations)
    initial = session._last_repair
    if initial is not None and initial.accepted:
        identity = initial.as_dict()["original_sha256"][:16]
        original = (
            f"{initial.original_answer.rstrip()}\n\n"
            f"{evidence.markdown_report(initial.initial_report.report())}\n"
        )
        session.store.save_report(f"overview-initial-{identity}", original)
    session.store.save_report("overview", report)
    if session.repair_citations and session.on_text is not None:
        session.on_text(report)
    return report


def why(session: Session, target: str) -> str:
    return session.run(prompts.WHY.format(target=target, language=session.settings.language))


def decisions(session: Session) -> str:
    """Reconstruct the project's decisions as structured records, saved as JSON and Markdown."""
    recorded: list[Decision] = []

    def record_decision(**fields: Any) -> str:
        """Record one technical decision of the project as an architecture decision record."""
        try:
            record = adrs.anchor_decision(
                Decision.model_validate(fields), session.profile.existing_adrs
            )
        except ValidationError as exc:
            raise ToolError(f"Invalid record, fix it and call again:\n{exc}") from exc
        previous = next(
            (
                i for i, value in enumerate(recorded)
                if value.title.casefold() == record.title.casefold()
            ),
            None,
        )
        if previous is None:
            recorded.append(record)
        else:
            recorded[previous] = record
        return f"Recorded decision: {record.title}"

    tool = beta_tool(record_decision, input_schema=Decision)
    synthesis = session.run(
        prompts.DECISIONS.format(language=session.settings.language), [tool], check=False
    )
    if not recorded:
        raise AgentError("L'analyse n'a produit aucune décision structurée. Relancer la demande.")
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
    if not recorded:
        raise AgentError(
            "L'analyse n'a produit aucune recommandation structurée. Relancer la demande."
        )
    recorded = recommendations.ordered(recorded)
    session.store.save_recommendations(recorded)
    report = session.checked(recommendations.markdown(recorded, synthesis))
    session.store.save_report("review", report)
    return report
