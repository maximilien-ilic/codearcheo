import pytest
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from learn_it.agent.tools import ProjectTools
from learn_it.analyzers import scan


@pytest.fixture
def tools(project):
    return ProjectTools(project.root)


def test_every_tool_has_a_schema_built_from_its_docstring(tools):
    for fn in tools.exploration():
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


@pytest.mark.parametrize("use_git", [True, False])
def test_exploration_excludes_symlinks(project, tmp_path, use_git):
    root = project.root if use_git else tmp_path / "plain"
    root.mkdir(exist_ok=True)
    private = tmp_path / "private.txt"
    private.write_text("PRIVATE_CANARY\n")
    (root / "notes.txt").symlink_to(private)
    hidden = root / "ignored.txt"
    hidden.write_text("IGNORED_CANARY\n")
    (root / "alias.txt").symlink_to(hidden)
    if use_git:
        (root / ".gitignore").write_text(".env\nignored.txt\n")
    tools = ProjectTools(root)

    assert "notes.txt" not in tools.list_files().splitlines()
    assert "alias.txt" not in tools.list_files().splitlines()
    assert "PRIVATE_CANARY" not in tools.search_code("PRIVATE_CANARY")
    for path in ("notes.txt", "alias.txt"):
        with pytest.raises(ToolError):
            tools.read_file(path)


def test_inventory_does_not_follow_replaced_directories(project, tmp_path):
    from learn_it import git
    from learn_it.analyzers import inventory

    folder = project.root / "config"
    folder.mkdir()
    manifest = folder / "package.json"
    manifest.write_text('{}')
    git.run(project.root, "add", "config/package.json")
    manifest.unlink()
    folder.rmdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "package.json").write_text('{"dependencies":{"private-canary":"1"}}')
    folder.symlink_to(external, target_is_directory=True)

    assert "config/package.json" not in inventory.list_files(project.root)
    assert "private-canary" not in scan(project).model_dump_json()


def test_git_internals_and_secret_directories_are_off_limits(project):
    from learn_it.analyzers import inventory

    nested = project.root / "nested" / ".git"
    nested.mkdir(parents=True)
    (nested / "config").write_text("INTERNAL_CANARY\n")
    secret = project.root / "secrets.key"
    secret.mkdir()
    (secret / "config").write_text("SECRET_CANARY\n")
    tools = ProjectTools(project.root)

    assert "nested/.git/config" not in inventory.list_files(project.root)
    assert "secrets.key/config" not in inventory.list_files(project.root)
    assert tools.search_code("INTERNAL_CANARY|SECRET_CANARY") == "No matches."
    for path in ("nested/.git/config", "secrets.key/config"):
        with pytest.raises(ToolError):
            tools.read_file(path)
