import json

import pytest
from anthropic.lib.tools import ToolError
from typer.testing import CliRunner

from learn_it import cli, features, recommendations
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.domain import Recommendation
from learn_it.features import Session
from learn_it.store import Store


def recommendation(**updates):
    values = dict(
        title="Simplifier la configuration", decision="Configuration globale",
        verdict="improve", reasons=["Deux paramètres contradictoires."], proposal="Unifier.",
        effort="S", impact="high", first_steps=["Ajouter un test."], evidence=["`app.py:1`"],
    )
    return Recommendation(**(values | updates))


def test_review_records_json_and_sorts_plan(project, monkeypatch):
    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        record.call(recommendation(title="Second", impact="low").model_dump())
        record.call(recommendation(title="First").model_dump())
        return "Deux améliorations possibles."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    report = features.review(session)
    assert report.index("## First") < report.index("## Second")
    assert [r.title for r in session.store.load_recommendations()] == ["First", "Second"]
    assert "citation(s) vérifiée(s)" in report


def test_review_cli_focuses_on_the_selected_directory(project, monkeypatch):
    (project.root / "src").mkdir()
    (project.root / "src/app.py").write_text("app = None\n")

    def fake(system, task, tools, settings, on_tool=None):
        assert 'project-relative path "src"' in task
        assert "cite evidence from it" in task
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        record.call(recommendation(evidence=["src/app.py:1"]).model_dump())
        return "Revue du code applicatif."

    monkeypatch.setattr(features, "run_agent", fake)
    result = CliRunner().invoke(cli.app, [
        "review", "-p", str(project.root), "--path", "./src/",
    ])
    assert result.exit_code == 0, result.output
    report = (project.root / ".learn-it/review.md").read_text()
    assert '    "src"' in report
    assert "src/app.py:1" in report


@pytest.mark.parametrize("path", ["src", "src/module.py"])
def test_scoped_review_requires_verifiable_evidence_in_scope(project, monkeypatch, path):
    for directory in ("src", "src_other"):
        (project.root / directory).mkdir()
        (project.root / directory / "module.py").write_text("value = 1\n")

    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        for reference in ("src_other/module.py:1", "src/module.py:2"):
            with pytest.raises(ToolError, match="verifiable citation"):
                record.call(recommendation(evidence=[reference]).model_dump())
        record.call(recommendation(evidence=["src/module.py:1", "app.py:1"]).model_dump())
        return "Revue ciblée."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    features.review(session, path=path)
    assert len(session.store.load_recommendations()) == 1


@pytest.mark.parametrize("path", ["app", ".env", "../shop", "/tmp", "alias"])
def test_inaccessible_review_path_stops_before_generation(project, monkeypatch, path):
    (project.root / "alias").symlink_to(project.root / "app.py")
    def unexpected(*args, **kwargs):
        pytest.fail("unexpected model call")

    monkeypatch.setattr(features, "run_agent", unexpected)
    result = CliRunner().invoke(cli.app, ["review", "-p", str(project.root), "--path", path])
    assert result.exit_code == 1
    assert "Périmètre de revue inaccessible" in result.output


def test_publication_never_happens_without_confirmation(project, monkeypatch):
    def forbidden(*args):
        pytest.fail("A network call was made without confirmation")

    monkeypatch.setattr(recommendations, "_gh", forbidden)
    with pytest.raises(ValueError, match="confirmation"):
        recommendations.publish(project, [recommendation()])


def test_an_improvement_must_have_an_actionable_first_step():
    with pytest.raises(ValueError, match="proposal"):
        recommendation(first_steps=[])
    with pytest.raises(ValueError, match="blank"):
        recommendation(evidence=[""])


def test_a_prose_only_review_never_erases_previous_recommendations(project, monkeypatch):
    from learn_it.agent.runner import AgentError

    store = Store(project.root)
    store.save_recommendations([recommendation()])
    monkeypatch.setattr(features, "run_agent", lambda *args, **kwargs: "Just prose.")
    with pytest.raises(AgentError, match="aucune recommandation"):
        features.review(Session(project, scan(project), store, Settings()))
    assert len(store.load_recommendations()) == 1


def test_publication_deduplicates_and_skips_keep_verdict(project, monkeypatch):
    from dataclasses import replace

    calls = []
    item = recommendation()
    project = replace(project, origin="https://github.com/owner/repo")

    def fake(*args):
        calls.append(args)
        if args[1] == "list":
            return json.dumps([{"body": recommendations._marker(item), "url": "existing"}])
        pytest.fail("Should reuse the existing issue")

    monkeypatch.setattr(recommendations, "_gh", fake)
    assert recommendations.publish(
        project, [item, recommendation(title="Keep", verdict="keep")], confirmed=True
    ) == ["existing"]
    assert len(calls) == 1
