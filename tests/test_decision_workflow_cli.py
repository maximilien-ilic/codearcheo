import json

import pytest
from typer.testing import CliRunner

from codearcheo import features, git, recommendations
from codearcheo.analyzers import scan
from codearcheo.cli import app
from codearcheo.config import Settings
from codearcheo.domain import Decision
from codearcheo.features import Session
from codearcheo.store import Store
from tests.test_recommendations import recommendation


def record(title="Choice", **updates):
    return Decision(**(dict(
        title=title, category="architecture", context="Context", decision="Choose this.",
        rationale="Reason", rationale_source="inferred", consequences=["Effect"],
        evidence=["`app.py:1`"],
    ) | updates))


def test_cli_exports_decisions_without_touching_existing_adrs(project, monkeypatch):
    def fake(session):
        session.store.save_decisions([record()])
        return "Ready"

    monkeypatch.setattr(features, "decisions", fake)
    result = CliRunner().invoke(app, ["decisions", "-p", str(project.root), "--export", "docs/adr"])
    assert result.exit_code == 0, result.output
    assert (project.root / "docs/adr/0001-choice.md").is_file()


@pytest.mark.parametrize("answer,expected", [("n\n", 0), ("y\n", 1)])
def test_cli_issue_creation_requires_a_positive_answer(project, monkeypatch, answer, expected):
    def fake(session, *, path):
        assert path is None
        session.store.save_recommendations([recommendation()])
        return "Review preview"

    calls = []
    monkeypatch.setattr(features, "review", fake)
    monkeypatch.setattr(recommendations, "publish", lambda *a, **kw: calls.append(kw) or [])
    result = CliRunner().invoke(app, ["review", "-p", str(project.root), "--issues"], input=answer)
    assert result.exit_code == 0, result.output
    assert len(calls) == expected
    if calls:
        assert calls[0] == {"confirmed": True}


def test_diff_cli_outputs_json_without_model_calls(project):
    first = git.run(project.root, "rev-list", "--max-parents=0", "HEAD").strip()
    result = CliRunner().invoke(app, ["diff", first, "-p", str(project.root), "--json"])
    assert result.exit_code == 0, result.output
    assert "FastAPI" in json.loads(result.stdout)["technologies_added"]


@pytest.mark.parametrize("command", ["scan", "diff", "serve"])
def test_offline_commands_work_with_a_claude_code_output_limit(project, monkeypatch, command):
    monkeypatch.setenv("CODEARCHEO_BACKEND", "claude-code")
    monkeypatch.setenv("CODEARCHEO_MAX_OUTPUT_TOKENS", "20")
    if command == "scan":
        args = ["scan", str(project.root), "--json"]
    elif command == "diff":
        args = ["diff", "HEAD", "-p", str(project.root), "--json"]
    else:
        from codearcheo import mcp_server

        served = []
        monkeypatch.setattr(mcp_server, "serve", served.append)
        monkeypatch.setenv("CODEARCHEO_CACHE_DIR", str(project.root / "cache"))
        args = ["serve", "-p", str(project.root)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    if command == "serve":
        assert len(served) == 1
        assert served[0].project.root == project.root
        assert served[0].profile.head == git.head(project.root)
        assert served[0].settings.cache_dir == project.root / "cache"


def test_existing_adr_overrides_an_inferred_label_in_agent_record(project, monkeypatch):
    path = project.root / "docs/adr/0001-choice.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Choice\n\n## Context\nNeed a choice.\n\n## Decision\nChoose this.\n")

    def fake(system, task, tools, settings, on_tool=None):
        tool = next(t for t in tools if getattr(t, "name", "") == "record_decision")
        tool.call(record().model_dump())
        return "Choice explained."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    features.decisions(session)
    actual = session.store.load_decisions()[0]
    assert actual.rationale_source == "documented"
    assert any("docs/adr/0001-choice.md" in evidence for evidence in actual.evidence)


def test_analysis_changed_during_agent_run_is_not_archived_under_old_sha(project, monkeypatch):
    (project.root / "notes.md").unlink()
    session = Session(project, scan(project), Store(project.root), Settings())
    assert not session.profile.uncommitted

    def fake(system, task, tools, settings, on_tool=None):
        (project.root / "app.py").write_text("# Changed during analysis\n")
        tool = next(t for t in tools if getattr(t, "name", "") == "record_decision")
        tool.call(record().model_dump())
        return "New decision."

    monkeypatch.setattr(features, "run_agent", fake)
    features.decisions(session)
    assert session.store.load_decisions()
    assert session.store.history_decisions(session.profile.head) is None


def test_a_prose_only_analysis_never_erases_previous_decisions(project, monkeypatch):
    from codearcheo.agent.runner import AgentError

    store = Store(project.root)
    store.save_decisions([record()])
    monkeypatch.setattr(features, "run_agent", lambda *args, **kwargs: "Just prose.")
    with pytest.raises(AgentError, match="aucune décision"):
        features.decisions(Session(project, scan(project), store, Settings()))
    assert len(store.load_decisions()) == 1
