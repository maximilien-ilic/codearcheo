import json

import pytest

from learn_it import features, recommendations
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


def test_publication_never_happens_without_confirmation(project, monkeypatch):
    def forbidden(*args):
        pytest.fail("A network call was made without confirmation")

    monkeypatch.setattr(recommendations, "_gh", forbidden)
    with pytest.raises(ValueError, match="confirmation"):
        recommendations.publish(project, [recommendation()])


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
