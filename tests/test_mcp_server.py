import asyncio
import json

import pytest

from learn_it.analyzers import code, scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store

pytest.importorskip("mcp")

from learn_it.mcp_server import build_server  # noqa: E402


def test_server_exposes_profile_decisions_and_exploration_tools(project):
    server = build_server(Session(project, scan(project), Store(project.root), Settings()))

    names = {tool.name for tool in asyncio.run(server.list_tools())}

    assert names == {
        "project_profile", "project_decisions", "list_files", "search_code", "read_file",
        "git_log", "git_show", "git_blame",
    } | ({"find_symbol", "module_dependencies"} if code.available() else set())


def test_profile_tool_follows_work_in_progress(project):
    """A long-lived MCP session must not serve the profile computed when it started."""
    server = build_server(Session(project, scan(project), Store(project.root), Settings()))
    files = scan(project).files
    (project.root / "worker.py").write_text("import redis\n")

    result = asyncio.run(server.call_tool("project_profile", {}))

    assert json.loads(result.content[0].text)["files"] == files + 1


def test_serve_reuses_the_profile_its_parent_just_computed(project, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from learn_it import analyzers, cli, mcp_server

    profile = scan(project)
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json())
    served = []
    monkeypatch.setattr(mcp_server, "serve", served.append)
    monkeypatch.setattr(analyzers, "scan", lambda _: pytest.fail("serve rescanned"))

    result = CliRunner().invoke(
        cli.app, ["serve", "-p", str(project.root), "--profile-file", str(path)]
    )

    assert result.exit_code == 0, result.output
    assert served[0].profile.model_dump() == profile.model_dump()
