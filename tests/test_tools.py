import pytest
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from learn_it.agent.tools import ProjectTools
from learn_it.analyzers import scan


@pytest.fixture
def tools(project):
    return ProjectTools(project.root, scan(project))


def test_every_tool_has_a_schema_built_from_its_docstring(tools):
    for fn in [tools.project_profile, *tools.exploration()]:
        spec = beta_tool(fn).to_dict()
        assert spec["description"]
        assert spec["input_schema"]["type"] == "object"
    search = beta_tool(tools.search_code).to_dict()["input_schema"]
    assert search["required"] == ["regex"]
    assert "Extended regular expression" in search["properties"]["regex"]["description"]


def test_list_and_search_skip_secrets(tools):
    assert ".env" not in tools.list_files().splitlines()
    assert "notes.md" in tools.list_files("*.md")  # untracked work is visible
    assert "app.py:3:" in tools.search_code(r"FastAPI\(")
    assert tools.search_code("sk_live") == "No matches."


def test_read_file_returns_numbered_lines(tools):
    assert "    3  app = FastAPI()" in tools.read_file("app.py", 3, 3)


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", ".env", ".git/config"])
def test_read_file_stays_inside_the_project(tools, path):
    with pytest.raises(ToolError):
        tools.read_file(path)


def test_git_tools_trace_a_decision(tools):
    log = tools.git_log(grep="flask")
    assert "Switch from Flask to FastAPI" in log
    sha = log.split()[0]
    assert "async support" in tools.git_show(sha)
    assert "+from fastapi import FastAPI" in tools.git_show(sha, patch=True)
    assert sha in tools.git_blame("app.py", 3, 3)


def test_git_show_refuses_options(tools):
    with pytest.raises(ToolError):
        tools.git_show("--output=/tmp/pwned")
