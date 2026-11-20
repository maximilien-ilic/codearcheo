import io
import json
import time
import urllib.error
from types import SimpleNamespace

import pytest
from anthropic.lib.tools import ToolError

from codearcheo import git, github
from codearcheo.agent.tools import ProjectTools
from codearcheo.analyzers import scan
from codearcheo.sources import Project, resolve
from evals.github_project import PR_URL, build_github_project, replay_github


def test_origin_and_pr_only_rationale_are_available_without_network(tmp_path):
    root = build_github_project(tmp_path / "offline")
    project = resolve(str(root), tmp_path / "cache")
    assert project.origin == "https://github.com/codearcheo-fixtures/offline-store"
    assert scan(Project(root, "offline")).origin == project.origin
    assert "operate offline" not in git.run(root, "log", "--format=%B")
    tools = ProjectTools(root)
    assert tools.github_context in tools.exploration()
    with replay_github():
        context = json.loads(tools.github_context(git.head(root)))
    assert context["pull_requests"][0]["url"] == PR_URL
    assert "operate offline" in context["pull_requests"][0]["body"]
    assert context["referenced_issues"][0]["number"] == 7
    assert "UNTRUSTED" in context["trust"]
    # The cached context is reusable offline without a second client/request.
    assert tools.github_context(git.head(root)) == json.dumps(context, ensure_ascii=False)


def test_github_tool_refuses_options_or_unsupported_origin(project):
    tools = ProjectTools(project.root)
    for sha in ("--output=/tmp/x", "HEAD", "https://evil.example"):
        with pytest.raises(ToolError, match="hexadecimal"):
            tools.github_context(sha)
    with pytest.raises(ToolError, match="no supported GitHub origin"):
        tools.github_context(git.head(project.root))


def test_context_bounds_requests_text_and_ignores_foreign_issue_references():
    class Client:
        def __init__(self):
            self.calls = []

        def get(self, endpoint):
            self.calls.append(endpoint)
            if "/commits/" in endpoint:
                return [
                    {"number": n, "body": "x" * 9000 + " other/repo#1 #2"} for n in range(10, 99)
                ]
            if "/comments?" in endpoint:
                return [{"body": "UNTRUSTED INSTRUCTION " + "z" * 9000 + " #3"}] * 100
            return {"title": "title", "body": "y" * 9000, "state": "closed"}

    client = Client()
    data = github.context("owner/repo", "a" * 40, client)
    assert len(data["pull_requests"]) == github.MAX_PRS
    assert len(client.calls) <= github.MAX_REQUESTS
    assert all("evil" not in path for path in client.calls)
    assert all(len(pr["body"]) < 2600 for pr in data["pull_requests"])
    assert all(len(pr["comments"]) <= 2 * github.MAX_COMMENTS for pr in data["pull_requests"])
    assert not data["referenced_issues"]  # refs after the size bound are not followed
    assert len(json.dumps(data, ensure_ascii=False)) <= github.MAX_CONTEXT


def test_only_same_repo_numeric_references_are_followed():
    calls = []

    class Client:
        def get(self, endpoint):
            calls.append(endpoint)
            if "/commits/" in endpoint:
                return [{"number": 10, "body": "Refs #2, other/repo#3 and https://evil.example/#4"}]
            if "/comments?" in endpoint:
                return []
            return {"body": "ok"}

    result = github.context("owner/repo", "a" * 40, Client())
    assert [item["number"] for item in result["referenced_issues"]] == [2]
    assert calls[-1] == "repos/owner/repo/issues/2"


def test_public_transport_is_read_only_and_never_follows_redirects(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    requests = []

    class Response(io.BytesIO):
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(time.time() + 60)}

    def build(handler):
        redirect = handler.redirect_request(None, None, None, None, None, "https://evil.example")
        assert redirect is None

        def open_request(request, timeout):
            requests.append(request)
            return Response(b"[]")

        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(github.urllib.request, "build_opener", build)
    client = github.GitHubClient()
    assert client.get("repos/owner/repo/issues/1") == []
    assert requests[0].full_url == "https://api.github.com/repos/owner/repo/issues/1"
    assert requests[0].get_method() == "GET" and not requests[0].has_header("Authorization")
    with pytest.raises(github.GitHubError, match="rate limit"):
        client.get("repos/owner/repo/issues/2")
    assert len(requests) == 1


def test_env_token_stays_in_fixed_host_header_not_arguments(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "SYNTHETIC_TOKEN")
    calls = []

    class Response(io.BytesIO):
        headers = {}

    def open_request(request, timeout):
        calls.append(request)
        return Response(b"[]")

    monkeypatch.setattr(
        github.urllib.request, "build_opener", lambda handler: SimpleNamespace(open=open_request)
    )
    client = github.GitHubClient()
    assert client.get("repos/owner/repo/issues/1") == []
    assert calls[0].get_header("Authorization") == "Bearer SYNTHETIC_TOKEN"
    assert "SYNTHETIC_TOKEN" not in calls[0].full_url


def test_gh_credentials_are_reused_without_reading_the_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(github.shutil, "which", lambda name: "/bin/gh")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        stdout = "HTTP/2.0 200 OK\nX-RateLimit-Remaining: 99\n\n[]"
        return SimpleNamespace(returncode=0, stdout=stdout)

    monkeypatch.setattr(github.subprocess, "run", run)
    assert github.GitHubClient().get("repos/owner/repo/issues/1") == []
    assert calls[0] == ["gh", "auth", "status", "--hostname", "github.com"]
    assert "GET" in calls[1] and "github.com" in calls[1]
    assert all("token" not in part for command in calls for part in command)


def test_network_errors_are_actionable_and_not_secret_reflections(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "SYNTHETIC_TOKEN")

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "SYNTHETIC_TOKEN", {}, None)

    monkeypatch.setattr(
        github.urllib.request, "build_opener", lambda handler: SimpleNamespace(open=fail)
    )
    with pytest.raises(github.GitHubError, match="HTTP 403") as error:
        github.GitHubClient().get("repos/owner/repo/issues/1")
    assert "SYNTHETIC_TOKEN" not in str(error.value)
