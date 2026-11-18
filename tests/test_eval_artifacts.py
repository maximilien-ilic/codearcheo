"""Measurements retain their inputs and outputs without requiring another model call."""

import copy
import json

import pytest

from evals import rescore, run
from learn_it.agent.runner import AgentError
from learn_it.domain import Decision


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    workdir = tmp_path / "cache" / "evals"
    monkeypatch.setenv("LEARN_IT_CACHE_DIR", str(workdir.parent))
    spec = {
        "name": "reference", "source": "synthetic", "language": "Python",
        "cases": [
            {"id": name, "command": "ask", "question": name, "mention": ["FastAPI"],
             "cite_any_file": ["app.py"]}
            for name in ("first", "second")
        ],
    }
    monkeypatch.setattr(run, "load_cases", lambda: [spec])
    monkeypatch.setattr(run.features, "ask", lambda *a: "FastAPI dans `app.py:3`.")
    return workdir, spec


def load_report(workdir):
    path, = workdir.glob("results-*.json")
    return path, json.loads(path.read_text())


def test_an_interruption_keeps_the_completed_answer_and_case_definition(evaluation, monkeypatch):
    workdir, spec = evaluation

    def answer(session, question):
        if question == "second":
            raise KeyboardInterrupt
        return "FastAPI dans `app.py:3`."

    monkeypatch.setattr(run.features, "ask", answer)
    with pytest.raises(KeyboardInterrupt):
        run.main([])

    _, report = load_report(workdir)
    assert not report["complete"]
    assert report["selected_cases"] == ["first", "second"]
    assert len(report["results"]) == 1
    result = report["results"][0]
    assert result["answer"] == "FastAPI dans `app.py:3`."
    assert result["case_definition"] == spec["cases"][0]
    assert result["status"] == "passed"


def test_case_selection_avoids_other_generations_and_keeps_separate_runs(evaluation, monkeypatch):
    workdir, _ = evaluation
    seen = []

    def answer(session, question):
        seen.append(question)
        return f"FastAPI dans `app.py:3`, réponse {len(seen)}."

    monkeypatch.setattr(run.features, "ask", answer)
    assert run.main([], case_ids=["second"]) == 0
    assert run.main([], case_ids=["second"]) == 0

    assert seen == ["second", "second"]
    reports = [json.loads(path.read_text()) for path in workdir.glob("results-*.json")]
    assert len(reports) == 2
    assert {r["results"][0]["answer"] for r in reports} == {
        "FastAPI dans `app.py:3`, réponse 1.", "FastAPI dans `app.py:3`, réponse 2.",
    }


@pytest.mark.parametrize("names,ids", [(["missing"], []), ([], ["missing"])])
def test_invalid_selection_stops_before_preparation(evaluation, monkeypatch, names, ids):
    monkeypatch.setattr(run, "prepare", lambda *a: pytest.fail("must not prepare or generate"))
    assert run.main(names, case_ids=ids) == 2


def test_backend_errors_are_distinct_from_quality_failures(evaluation, monkeypatch, capsys):
    workdir, _ = evaluation

    def answer(session, question):
        if question == "second":
            raise AgentError("quota atteint")
        return "FastAPI dans `app.py:3`."

    monkeypatch.setattr(run.features, "ask", answer)
    assert run.main([]) == 1

    _, report = load_report(workdir)
    assert report["complete"]
    assert [r["status"] for r in report["results"]] == ["passed", "error"]
    assert report["results"][1]["error"] == "quota atteint"
    assert "answer" not in report["results"][1]
    output = capsys.readouterr().out
    assert "Qualité : 1/1 réponses évaluables ; 1 réponse(s) indisponible(s)." in output


def test_decision_records_are_archived_independently_of_the_mutable_store(evaluation, monkeypatch):
    workdir, spec = evaluation
    spec["cases"] = [{"id": "decisions", "command": "decisions"}]

    def decisions(session):
        session.store.save_decisions([Decision(
            title="FastAPI", category="framework", context="Async", decision="FastAPI",
            rationale="Async endpoints", rationale_source="inferred", consequences=[],
            evidence=["app.py:3"],
        )])
        return "FastAPI."

    monkeypatch.setattr(run.features, "decisions", decisions)
    assert run.main([]) == 0
    _, report = load_report(workdir)
    saved = report["results"][0]["decisions"]
    assert saved[0]["title"] == "FastAPI"

    (workdir / "reference/.learn-it/decisions.json").write_text("[]")
    assert rescore.rescore(report, workdir)["results"][0]["passed"]


def test_rescoring_reuses_the_saved_definition_and_never_regenerates(evaluation, monkeypatch):
    workdir, _ = evaluation
    assert run.main([]) == 0
    source, report = load_report(workdir)
    original = source.read_bytes()
    monkeypatch.setattr(run.features, "ask", lambda *a: pytest.fail("no model calls in rescore"))
    monkeypatch.setattr(run, "load_cases", lambda: pytest.fail("use archived expectations"))

    assert rescore.main(source) == 0
    assert source.read_bytes() == original
    rescored = json.loads(next(workdir.glob("rescore-*.json")).read_text())
    assert [r["answer"] for r in rescored["results"]] == [r["answer"] for r in report["results"]]
    assert all(r["previous_passed"] and r["passed"] for r in rescored["results"])


def test_rescoring_refuses_changed_source_even_at_the_same_commit(evaluation):
    workdir, _ = evaluation
    assert run.main([], case_ids=["first"]) == 0
    source, _ = load_report(workdir)
    (workdir / "reference/app.py").write_text("a completely different implementation\n")

    assert rescore.main(source) == 2
    assert not list(workdir.glob("rescore-*.json"))


def test_rescoring_preserves_instrumentation_failures(evaluation):
    workdir, _ = evaluation
    assert run.main([], case_ids=["first"]) == 0
    _, report = load_report(workdir)
    report = copy.deepcopy(report)
    report["results"][0].update(passed=False, status="failed")
    report["results"][0]["checks"].append({
        "name": "correction/comparaison disponible", "ok": False, "detail": "missing metadata",
    })

    graded = rescore.rescore(report, workdir)
    assert not graded["results"][0]["passed"]


def test_old_reports_cannot_be_rescored_without_original_answers(tmp_path):
    source = tmp_path / "old.json"
    source.write_text('{"results": []}')
    assert rescore.main(source) == 2
    assert not list(tmp_path.glob("rescore-*.json"))
