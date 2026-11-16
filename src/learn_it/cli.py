"""Command-line interface."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, NoReturn

import anthropic
import typer
from rich.markup import escape

from learn_it import analyzers, features, git, render, sources
from learn_it.agent.runner import AgentError
from learn_it.config import Settings
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


def _session(target: str) -> Session:
    """Resolve the project and profile it afresh.

    A project in progress changes between two commands, committed or not, with or without
    git. Rescanning costs well under a second even on repositories with thousands of commits,
    against tens of seconds for the agent, so no cached profile can go stale.
    """
    settings = Settings.from_env()
    project = sources.resolve(target, settings.cache_dir)
    store = Store(project.root)
    profile = analyzers.scan(project)
    store.save_profile(profile)
    return Session(project, profile, store, settings, on_tool=render.tool_call)


def _run_agent(target: str, work: str, feature, *args: str) -> str:
    with _friendly_errors():
        session = _session(target)
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
) -> None:
    """Pose une question sur le projet : réponse sourcée (fichier:ligne, commit)."""
    render.markdown(_run_agent(project, "explore le projet", features.ask, question))


@app.command()
def overview(project: ProjectOption = ".") -> None:
    """Guide d'onboarding : architecture, flux clés, carte du code, ordre de lecture."""
    render.markdown(_run_agent(project, "cartographie le projet", features.overview))


@app.command()
def decisions(project: ProjectOption = ".") -> None:
    """Reconstitue les décisions techniques du projet (format ADR) : quoi, quand, pourquoi."""
    render.markdown(_run_agent(project, "reconstitue les décisions", features.decisions))


@app.command()
def why(
    target: Annotated[str, typer.Argument(help="Fichier, dossier, symbole, dépendance ou choix.")],
    project: ProjectOption = ".",
) -> None:
    """Explique pourquoi un élément du projet existe et pourquoi il est ainsi."""
    render.markdown(_run_agent(project, "remonte l'historique", features.why, target))


@app.command()
def review(project: ProjectOption = ".") -> None:
    """Évalue les décisions : garder, améliorer ou remplacer, avec effort, impact et plan."""
    render.markdown(_run_agent(project, "évalue les décisions", features.review))


@app.command()
def serve(project: ProjectOption = ".") -> None:
    """Serveur MCP (stdio) : donne les outils du projet à Claude Code, Cursor…"""
    from learn_it import mcp_server

    with _friendly_errors():
        session = _session(project)
    mcp_server.serve(session)
