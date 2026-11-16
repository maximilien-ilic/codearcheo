"""Command-line interface."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, NoReturn

import anthropic
import typer
from rich.markup import escape

from learn_it import analyzers, features, git, recommendations, render, sources, timeline
from learn_it.agent.runner import AgentError
from learn_it.config import Settings
from learn_it.export import export_decisions
from learn_it.features import Session
from learn_it.store import Store

app = typer.Typer(
    help="Interroge un projet, comprends ses décisions techniques, améliore-les.",
    no_args_is_help=True,
    add_completion=False,
)

ProjectOption = Annotated[
    str, typer.Option("--project", "-p", help="Dossier local ou URL GitHub (défaut : ici).")
]
ModelOption = Annotated[
    str | None, typer.Option("--model", help="Modèle Claude pour cette commande.")
]
EffortOption = Annotated[
    str | None, typer.Option("--effort", help="low, medium, high, xhigh, max ; vide pour omettre.")
]
BudgetOption = Annotated[
    int | None,
    typer.Option(
        "--budget", min=20_000, help="Budget API indicatif en tokens, pas un plafond USD."
    ),
]


def _fail(message: str) -> NoReturn:
    render.err.print(f"[red]✗[/red] {escape(message)}")
    raise typer.Exit(1)


@contextmanager
def _friendly_errors() -> Iterator[None]:
    try:
        yield
    except anthropic.AuthenticationError:
        _fail("Clé API refusée : vérifie ANTHROPIC_API_KEY (ou lance `ant auth login`).")
    except anthropic.APIConnectionError:
        _fail("Impossible de joindre l'API Claude : vérifie ta connexion.")
    except anthropic.APIStatusError as exc:
        _fail(f"Erreur de l'API Claude ({exc.status_code}) : {exc.message}")
    except anthropic.AnthropicError as exc:  # e.g. no credentials at all
        _fail(f"{exc}\nExporte ANTHROPIC_API_KEY ou lance `ant auth login`.")
    except (AgentError, OSError, ValueError, git.GitError) as exc:
        _fail(str(exc))


def _session(
    target: str, *, model: str | None = None, effort: str | None = None, budget: int | None = None
) -> Session:
    """Resolve the project and profile it afresh.

    A project in progress changes between two commands, committed or not, with or without
    git. Rescanning costs well under a second even on repositories with thousands of commits,
    against tens of seconds for the agent, so no cached profile can go stale.
    """
    settings = Settings.from_env(model=model, effort=effort, budget=budget)
    project = sources.resolve(target, settings.cache_dir)
    store = Store(project.root)
    profile = analyzers.scan(project)
    store.save_profile(profile)
    return Session(project, profile, store, settings, on_tool=render.tool_call)


def _run_agent(
    target: str,
    work: str,
    feature,
    *args: str,
    model: str | None = None,
    effort: str | None = None,
    budget: int | None = None,
    stream: bool = False,
) -> str:
    with _friendly_errors():
        session = _session(target, model=model, effort=effort, budget=budget)
        if stream:
            from learn_it.chat import stream_text

            session.on_text = stream_text
            answer = feature(session, *args)
            stream_text("\n")
            return answer
        with render.err.status(f"Claude {work}…"):
            return feature(session, *args)


@app.command()
def scan(
    target: Annotated[str, typer.Argument(help="Dossier local ou URL GitHub.")] = ".",
    as_json: Annotated[bool, typer.Option("--json", help="Affiche le profil en JSON.")] = False,
) -> None:
    """Analyse sans IA : stack, dates d'adoption, historique, zones chaudes, travail en cours."""
    with _friendly_errors():
        settings = Settings.from_env()
        with render.err.status("Analyse du projet…"):
            project = sources.resolve(target, settings.cache_dir, update=True)
            profile = analyzers.scan(project)
        path = Store(project.root).save_profile(profile)
    if as_json:
        print(profile.model_dump_json(indent=2))
        return
    render.profile(profile)
    render.err.print(f"[dim]Profil enregistré dans {path}[/dim]")


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="Ta question, entre guillemets.")],
    project: ProjectOption = ".",
    model: ModelOption = None,
    effort: EffortOption = None,
    budget: BudgetOption = None,
    stream: Annotated[bool, typer.Option("--stream/--no-stream")] = True,
) -> None:
    """Pose une question sur le projet : réponse sourcée (fichier:ligne, commit)."""
    answer = _run_agent(
        project,
        "explore le projet",
        features.ask,
        question,
        model=model,
        effort=effort,
        budget=budget,
        stream=stream,
    )
    if not stream:
        render.markdown(answer)


@app.command()
def overview(
    project: ProjectOption = ".",
    model: ModelOption = None,
    effort: EffortOption = None,
    budget: BudgetOption = None,
) -> None:
    """Guide d'onboarding : architecture, flux clés, carte du code, ordre de lecture."""
    render.markdown(
        _run_agent(
            project,
            "cartographie le projet",
            features.overview,
            model=model,
            effort=effort,
            budget=budget,
        )
    )


@app.command()
def decisions(
    project: ProjectOption = ".",
    model: ModelOption = None,
    effort: EffortOption = None,
    budget: BudgetOption = None,
    export: Annotated[
        Path | None, typer.Option("--export", help="Dossier ADR dans le projet.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Remplacer un ADR du même titre.")] = False,
) -> None:
    """Reconstitue les décisions techniques du projet (format ADR) : quoi, quand, pourquoi."""
    if force and export is None:
        _fail("--force s'utilise avec --export.")
    with _friendly_errors():
        session = _session(project, model=model, effort=effort, budget=budget)
        with render.err.status("Claude reconstitue les décisions…"):
            report = features.decisions(session)
        render.markdown(report)
        if export is not None:
            paths = export_decisions(
                session.project.root, session.store.load_decisions(), export, force=force
            )
            for path in paths:
                render.err.print(f"ADR enregistré : {path}", markup=False)


@app.command()
def why(
    target: Annotated[str, typer.Argument(help="Fichier, dossier, symbole, dépendance ou choix.")],
    project: ProjectOption = ".",
    model: ModelOption = None,
    effort: EffortOption = None,
    budget: BudgetOption = None,
) -> None:
    """Explique pourquoi un élément du projet existe et pourquoi il est ainsi."""
    render.markdown(
        _run_agent(
            project,
            "remonte l'historique",
            features.why,
            target,
            model=model,
            effort=effort,
            budget=budget,
        )
    )


@app.command()
def review(
    project: ProjectOption = ".",
    model: ModelOption = None,
    effort: EffortOption = None,
    budget: BudgetOption = None,
    issues: Annotated[
        bool, typer.Option("--issues", help="Proposer la création de tickets.")
    ] = False,
) -> None:
    """Évalue les décisions : garder, améliorer ou remplacer, avec effort, impact et plan."""
    with _friendly_errors():
        session = _session(project, model=model, effort=effort, budget=budget)
        with render.err.status("Claude évalue les décisions…"):
            report = features.review(session)
        render.markdown(report)
        candidates = [r for r in session.store.load_recommendations() if r.verdict != "keep"]
        if issues and candidates:
            if typer.confirm(f"Publier jusqu'à {len(candidates)} ticket(s) sur l'origine GitHub ?"):
                for url in recommendations.publish(session.project, candidates, confirmed=True):
                    render.err.print(url, markup=False)
        elif issues:
            render.err.print("Aucune recommandation à publier.")


@app.command()
def diff(
    ref: Annotated[str | None, typer.Argument(help="Révision Git de référence.")] = None,
    project: ProjectOption = ".",
    as_json: Annotated[
        bool, typer.Option("--json", help="Changements structurés en JSON.")
    ] = False,
) -> None:
    """Technos et décisions ajoutées, retirées ou modifiées, sans appel IA."""
    import json

    with _friendly_errors():
        settings = Settings.from_env()
        target = sources.resolve(project, settings.cache_dir)
        changes = timeline.compare(target, Store(target.root), ref)
    output = (
        json.dumps(changes.as_dict(), ensure_ascii=False, indent=2)
        if as_json else changes.markdown()
    )
    print(output)


@app.command()
def chat(
    project: ProjectOption = ".",
    model: ModelOption = None,
    effort: EffortOption = None,
    budget: BudgetOption = None,
) -> None:
    """Conversation avec historique conservé, streaming et /save pour l'enregistrer."""
    from learn_it.chat import interactive

    with _friendly_errors():
        interactive(_session(project, model=model, effort=effort, budget=budget))


@app.command()
def serve(project: ProjectOption = ".") -> None:
    """Serveur MCP (stdio) : donne les outils du projet à Claude Code, Cursor…"""
    from learn_it import mcp_server

    with _friendly_errors():
        session = _session(project)
    mcp_server.serve(session)
