"""`codearcheo serve`: the project tools over MCP (stdio), for Claude Code, Cursor or any client."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from codearcheo import analyzers
from codearcheo.agent.tools import ProjectTools
from codearcheo.features import Session

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def serve(session: Session) -> None:
    build_server(session).run("stdio")


def build_server(session: Session) -> MCPServer:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        raise SystemExit(
            "`codearcheo serve` a besoin de l'extra mcp : uv tool install --editable '.[mcp]'"
        ) from None

    tools = ProjectTools(session.project.root)

    def project_profile() -> str:
        """The project's deterministic profile, recomputed at each call so that it follows work
        in progress: languages, stack with the commit that adopted each technology, activity,
        hotspots, docs and uncommitted work. Start here."""
        profile = analyzers.scan(session.project)
        session.store.save_profile(profile)
        return profile.model_dump_json(exclude_none=True)

    def project_decisions() -> str:
        """Technical decisions reconstructed by `codearcheo decisions`, as ADR-shaped JSON."""
        decisions = session.store.load_decisions()
        if not decisions:
            return "No decision recorded yet: run `codearcheo decisions` on this project."
        return json.dumps([d.model_dump() for d in decisions], ensure_ascii=False)

    server = MCPServer(
        name="codearcheo",
        instructions=(
            f"Read-only tools to understand the {session.profile.name} project in depth. "
            "Start with project_profile, search before reading, and use git_log, git_show and "
            "git_blame to find why the code is the way it is."
        ),
    )
    for fn in (project_profile, project_decisions, *tools.exploration()):
        server.add_tool(fn)
    return server
