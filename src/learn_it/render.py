"""Terminal output (Rich) and Markdown reports.

Reports go to stdout so they can be piped; progress and tool calls go to stderr.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table

from learn_it.domain import Decision, ProjectProfile

console = Console()
err = Console(stderr=True)


def _day(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d") if value else "?"


def profile(p: ProjectProfile) -> None:
    origin = f"  [dim]{p.origin}[/dim]" if p.origin else ""
    console.rule(f"[bold]{escape(p.name)}[/bold]{origin}")
    languages = ", ".join(f"{name} ({n})" for name, n in list(p.languages.items())[:6]) or "aucun"
    console.print(f"{p.files} fichiers · langages : {escape(languages)}")
    if p.commits:
        console.print(
            f"{p.commits} commit(s) · {p.contributors} contributeur(s) · "
            f"du {_day(p.first_commit)} au {_day(p.last_commit)}"
        )

    notable = [t for t in p.technologies if t.category != "library"]
    stack = [t for t in notable if not t.auxiliary]
    if stack:
        table = Table(title="Stack technique", title_justify="left", show_lines=False)
        for column in ("Techno", "Catégorie", "Détectée dans", "Adoptée"):
            table.add_column(column)
        for t in stack:
            adopted = (
                f"{_day(t.adopted.date)} · {t.adopted.sha[:7]} · {t.adopted.subject[:60]}"
                if t.adopted
                else "—"
            )
            table.add_row(escape(t.name), t.category, escape(t.source), escape(adopted))
        console.print(table)
    if auxiliary := [t for t in notable if t.auxiliary]:
        shown = ", ".join(f"{t.name} ({t.source})" for t in auxiliary)
        console.print(f"[bold]Exemples, tests et docs[/bold] : {escape(shown)}")
    if libraries := len(p.technologies) - len(notable):
        console.print(f"[dim]+ {libraries} autre(s) dépendance(s)[/dim]")

    if p.hotspots:
        table = Table(title="Zones chaudes : fichiers les plus modifiés", title_justify="left")
        table.add_column("Fichier")
        table.add_column("Commits", justify="right")
        for h in p.hotspots:
            table.add_row(escape(h.path), str(h.commits))
        console.print(table)
    if p.docs:
        shown = ", ".join(p.docs[:12]) + (" …" if len(p.docs) > 12 else "")
        console.print(f"[bold]Documentation[/bold] : {escape(shown)}")
    if p.uncommitted:
        count = len(p.uncommitted)
        console.print(f"[bold]Travail en cours[/bold] : {count} fichier(s) non commité(s)")


def markdown(text: str) -> None:
    console.print(Markdown(text))


def tool_call(name: str, arguments: dict[str, Any]) -> None:
    shown = ", ".join(f"{key}={value!r}" for key, value in arguments.items())
    err.print(f"[dim]  → {name}({escape(shown[:120])})[/dim]")


def decisions_markdown(decisions: list[Decision], synthesis: str) -> str:
    lines = ["# Décisions techniques", "", synthesis.strip(), ""]
    for i, d in enumerate(decisions, 1):
        source = "documentée" if d.rationale_source == "documented" else "déduite"
        meta = f"*{d.category}* · justification {source}"
        if d.introduced_in:
            meta += f" · introduite dans `{d.introduced_in[:7]}`"
        lines += [
            f"## {i}. {d.title}", "", meta, "",
            f"**Contexte.** {d.context}", "",
            f"**Décision.** {d.decision}", "",
            f"**Pourquoi.** {d.rationale}", "",
        ]
        if d.alternatives:
            lines += ["**Alternatives.**", *(f"- {a}" for a in d.alternatives), ""]
        lines += ["**Conséquences.**", *(f"- {c}" for c in d.consequences), ""]
        lines += ["**Sources.**", *(f"- {e}" for e in d.evidence), ""]
    return "\n".join(lines)
