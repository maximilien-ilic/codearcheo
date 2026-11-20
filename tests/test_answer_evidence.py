import pytest

from codearcheo import features
from codearcheo.analyzers import scan
from codearcheo.config import Settings
from codearcheo.features import Session
from codearcheo.store import Store


@pytest.mark.parametrize("command,args,filename", [
    (features.ask, ("question",), None),
    (features.why, ("app.py",), None),
    (features.overview, (), "overview.md"),
    (features.review, (), "review.md"),
])
def test_answers_warn_about_false_citations(project, monkeypatch, capsys, command, args, filename):
    def fake(system, task, tools, settings, on_tool=None):
        for tool in tools:
            if getattr(tool, "name", "") == "record_recommendation":
                tool.call(dict(
                    title="Keep", decision="Existing design", verdict="keep", reasons=["Fits"],
                    impact="low", effort="S", evidence=["`app.py:1`"],
                ))
        return "Voir `app.py:1` et `lost.py:12`."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    report = command(session, *args)
    assert "1 citation(s) vérifiée(s), 1 introuvable(s)" in report
    assert "lost.py:12" in capsys.readouterr().err
    if filename:
        assert (session.store.dir / filename).read_text() == report


def test_no_citations_is_also_reported(project, monkeypatch, capsys):
    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: "Une réponse sans preuve.")
    session = Session(project, scan(project), Store(project.root), Settings())
    assert "Aucune citation vérifiable" in features.ask(session, "question")
    assert "Aucune citation vérifiable" in capsys.readouterr().err


def test_streamed_answer_keeps_its_original_body_and_appends_only_the_check(project, monkeypatch):
    original = "Voir ci.yml:1."
    chunks = []

    def fake(*args, on_text=None, **kwargs):
        on_text(original[:8])
        on_text(original[8:])
        return original

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(
        project, scan(project), Store(project.root), Settings(), on_text=chunks.append
    )

    answer = features.ask(session, "question")

    assert "".join(chunks) == answer
    assert answer.startswith(original + "\n\n---")
    assert "1 introuvable(s)" in answer


def test_nonstreamed_answer_completes_a_unique_path_before_verifying(project, monkeypatch):
    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: "Voir ci.yml:1.")
    session = Session(project, scan(project), Store(project.root), Settings())

    answer = features.ask(session, "question")

    assert answer.startswith("Voir .github/workflows/ci.yml:1.")
    assert "0 introuvable(s)" in answer


@pytest.mark.parametrize("command", [features.decisions, features.review])
def test_structured_evidence_is_completed_in_json_and_markdown(project, monkeypatch, command):
    def fake(system, task, tools, settings, on_tool=None):
        for tool in tools:
            name = getattr(tool, "name", "")
            if name == "record_decision":
                tool.call(dict(
                    title="CI", category="infra", context="Tests", decision="Run tests",
                    rationale="Catch regressions", rationale_source="inferred", consequences=[],
                    evidence=["ci.yml:1"],
                ))
            elif name == "record_recommendation":
                tool.call(dict(
                    title="CI", decision="Run tests", verdict="keep", reasons=["Catch regressions"],
                    impact="low", effort="S", evidence=["ci.yml:1"],
                ))
        return "Voir ci.yml:1."

    monkeypatch.setattr(features, "run_agent", fake)
    store = Store(project.root)
    session = Session(project, scan(project), store, Settings())

    report = command(session)

    records = (store.load_decisions() if command is features.decisions
               else store.load_recommendations())
    assert records[0].evidence == [".github/workflows/ci.yml:1"]
    assert "0 introuvable(s)" in report
