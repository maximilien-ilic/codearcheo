import asyncio

import pytest

from learn_it.analyzers import scan
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
    }
