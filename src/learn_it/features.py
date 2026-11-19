"""Use cases. Each one is a task prompt that the agent runs over the project's tools.

Adding a feature: a prompt in `agent/prompts.py`, a function here, a command in `cli.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any

from anthropic import beta_tool
from anthropic.lib.tools import ToolError
from pydantic import ValidationError
from rich.markup import escape

from learn_it import evidence, recommendations, render
from learn_it.agent import prompts
from learn_it.agent.claude_code import run_claude_code
from learn_it.agent.limits import SessionLimits
from learn_it.agent.runner import (
    AgentError,
    TextCallback,
    Tool,
    ToolCallback,
    UsageCallback,
    run_agent,
)
from learn_it.agent.tools import ProjectTools
from learn_it.analyzers import adrs, code, inventory
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
    limits: SessionLimits | None = None
    _last_repair: RepairResult | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.limits is None and (
            self.settings.max_requests is not None or self.settings.max_output_tokens != 16_000
        ):
            self.limits = SessionLimits.from_settings(self.settings)

    @property
    def last_repair(self) -> dict[str, Any] | None:
        """A fresh view of immutable initial/final evidence metadata for offline comparisons."""
        return self._last_repair.as_dict() if self._last_repair is not None else None

    def checked(
        self, answer: str, *, repair: bool = False, normalize_paths: bool = True,
        scope: str | None = None,
    ) -> str:
        """Warn without hiding the answer; retain the same warning in saved reports."""
        # Answers still abbreviate some paths (`legacy.yml:33`): complete the unambiguous ones.
        # A live stream has already displayed its body; only append checks in that case.
        if normalize_paths:
            answer = evidence.complete_paths(
                answer, inventory.list_files(self.project.root), scope
            )
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
                invoke=self._repair_on_claude_code if self.settings.backend == "claude-code"
                else None,
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
        system = prompts.system(self.profile)
        if self.settings.backend == "claude-code":
            return self._run_claude_code(system, task, extra_tools, check=check)
        tools = ProjectTools(self.project.root).exploration()
        repair = self.repair_citations and check and not extra_tools
        buffered = buffer_text or repair
        options = {"on_text": self.on_text} if self.on_text is not None and not buffered else {}
        if self.on_usage is not None:
            options["on_usage"] = self.on_usage
        if self.limits is not None:
            options["limits"] = self.limits
        answer = run_agent(
            system, task, [*tools, *extra_tools], self.settings, self.on_tool, **options
        )
        if not check:
            return answer
        checked = self.checked(
            answer, repair=repair, normalize_paths=buffered or self.on_text is None
        )
        if self.on_text is not None:
            self.on_text(checked if buffered else checked[len(answer.rstrip()):])
        return checked

    def _run_claude_code(
        self, system: str, task: str, extra_tools: Sequence[Tool], *, check: bool
    ) -> str:
        """Same task on the Claude subscription: no streaming and no local limits."""
        options = {"on_usage": self.on_usage} if self.on_usage is not None else {}
        answer = run_claude_code(
            system, task, list(extra_tools), self.settings, root=self.project.root, **options
        )
        if not check:
            return answer
        checked = self.checked(answer, repair=self.repair_citations and not extra_tools)
        if self.on_text is not None:
            self.on_text(checked)
        return checked

    def _repair_on_claude_code(
        self, system: str, task: str, tools: Sequence[Tool], settings: Settings, *,
        single_request: bool = False, on_usage: UsageCallback | None = None, **_: Any,
    ) -> str:
        """The repair request without any tool; `claude -p` cannot cap its output."""
        return run_claude_code(
            system, task, list(tools),
            replace(settings, max_output_tokens=Settings.max_output_tokens),
            root=self.project.root, on_usage=on_usage, exploration=False,
        )


def _complete_evidence(
    fields: dict[str, Any], session: Session, scope: str | None = None,
) -> dict[str, Any]:
    """Structured records still abbreviate paths (`legacy.yml:33`); complete unique ones."""
    items = fields.get("evidence")
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        return fields  # let validation report the malformed record
    files = inventory.list_files(session.project.root)
    return {**fields, "evidence": [evidence.complete_paths(item, files, scope) for item in items]}


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
                Decision.model_validate(_complete_evidence(fields, session)),
                session.profile.existing_adrs,
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


def review(session: Session, *, path: str | None = None) -> str:
    root = session.project.root
    relative = PurePosixPath(path).as_posix() if path is not None else "."
    scope_label = json.dumps(relative, ensure_ascii=False) if relative != "." else None
    scope = ""
    scoped_files: set[str] = set()
    if scope_label is not None:
        if inventory.is_safe_path(root, relative):
            scoped_files = {
                name for name in inventory.list_files(root)
                if name == relative or name.startswith(relative + "/")
            }
        if not scoped_files:
            raise AgentError(
                f"Périmètre de revue inaccessible : {path!r}. "
                "Choisis un fichier ou dossier visible depuis la racine du projet."
            )
        scope = prompts.REVIEW_SCOPE.format(path=scope_label)

    known = session.store.load_decisions() if scope_label is None else []
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
            recommendation = Recommendation.model_validate(
                _complete_evidence(fields, session, relative if scoped_files else None)
            )
        except ValidationError as exc:
            raise ToolError(f"Invalid recommendation, fix it and call again:\n{exc}") from exc
        if scoped_files:
            citations = [
                citation for item in recommendation.evidence
                for citation in evidence.find_citations(item)
                if citation.path in scoped_files
            ]
            verified = evidence.verify_citations(citations, root)
            if not any(citation not in verified.problems for citation in citations):
                raise ToolError(
                    f"Include at least one verifiable citation (file:line) within {scope_label}."
                )
        recorded.append(recommendation)
        return f"Recorded recommendation {len(recorded)}: {recorded[-1].title}"

    tool = beta_tool(record_recommendation, input_schema=Recommendation)
    task = prompts.REVIEW.format(
        scope=scope, known_decisions=known_block, language=session.settings.language
    )
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
    if scope_label is not None:
        synthesis = f"**Périmètre de la revue**\n\n    {scope_label}\n\n{synthesis}"
    report = session.checked(
        recommendations.markdown(recorded, synthesis),
        scope=relative if scoped_files else None,
    )
    session.store.save_report("review", report)
    return report
