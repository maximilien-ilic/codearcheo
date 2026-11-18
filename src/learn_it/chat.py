"""Interactive questions using one agent conversation and one project profile."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable

import typer

from learn_it import render
from learn_it.agent import prompts
from learn_it.agent.limits import SessionLimitError
from learn_it.agent.runner import ConversationAgent
from learn_it.agent.tools import ProjectTools
from learn_it.features import Session


def stream_text(text: str) -> None:
    """Write raw Markdown incrementally; never render the completed answer a second time."""
    sys.stdout.write(text)
    sys.stdout.flush()


def interactive(session: Session, *, read: Callable[[], str] | None = None) -> None:
    read = read or (lambda: typer.prompt("Vous"))
    system = prompts.SYSTEM.format(profile=session.profile.model_dump_json(indent=1))
    options = {"limits": session.limits} if session.limits is not None else {}
    agent = ConversationAgent(
        system, ProjectTools(session.project.root).exploration(), session.settings, **options
    )
    render.err.print("Pose une question. /save enregistre la conversation, /exit termine.")
    try:
        while True:
            try:
                question = read().strip()
            except (EOFError, KeyboardInterrupt, typer.Abort):
                break
            if not question:
                continue
            if question in {"/exit", "/quit"}:
                break
            if question == "/save":
                path = session.store.save_report(f"chat-{uuid.uuid4().hex}", agent.markdown())
                render.err.print(f"Conversation enregistrée dans {path}", markup=False)
                continue
            try:
                answer = agent.ask(question, on_tool=session.on_tool, on_text=stream_text)
            except SessionLimitError as exc:
                render.err.print(str(exc), markup=False)
                render.err.print("/save reste disponible pour enregistrer, /exit pour terminer.")
                continue
            if isinstance(answer, str):
                checked = session.checked(answer, normalize_paths=False)
                stream_text(checked[len(answer.rstrip()):])
                agent.transcript[-1] = ("Claude", checked)
            stream_text("\n")
    finally:
        agent.close()
