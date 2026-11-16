import pytest

from learn_it import features
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store


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
