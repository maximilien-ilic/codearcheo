import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from learn_it import citation_repair, evidence, features
from learn_it.agent import runner
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.domain import Decision
from learn_it.features import Session
from learn_it.store import Store

ORIGINAL = "L'API utilise FastAPI (`app.py:3`) ; le module crée l'application (`app.py:999`)."
CORRECTED = ORIGINAL.replace("`app.py:999`", "`app.py:1-3`")


def plan(source="`app.py:999`", replacement="`app.py:1-3`"):
    return json.dumps({"edits": [{"citation": source, "replacement": replacement}]})


def session(project, **kwargs):
    return Session(project, scan(project), Store(project.root), Settings(), **kwargs)


def test_default_and_already_valid_answers_do_not_make_an_extra_request(project, monkeypatch):
    calls = []
    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: ORIGINAL)
    monkeypatch.setattr(citation_repair, "run_agent", lambda *a, **kw: calls.append(a))
    default = session(project)
    assert ORIGINAL in features.ask(default, "Comment ?")
    assert default.last_repair is None
    assert calls == []

    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: "FastAPI : `app.py:3`.")
    enabled = session(project, repair_citations=True)
    assert "FastAPI" in features.ask(enabled, "Comment ?")
    assert enabled.last_repair["attempted"] is False
    assert enabled.last_repair["before"] == {"total": 1, "valid": 1, "invalid": 0}
    assert calls == []


def test_repair_improves_only_invalid_references_and_preserves_initial_metrics(
    project, monkeypatch,
):
    calls = []
    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: ORIGINAL)

    def correct(system, task, tools, settings, **options):
        calls.append((system, json.loads(task), tools, settings, options))
        return plan()

    monkeypatch.setattr(citation_repair, "run_agent", correct)
    enabled = session(project, repair_citations=True)
    answer = features.why(enabled, "app.py")
    assert answer.startswith(CORRECTED)
    assert "Correction facultative" in answer
    assert len(calls) == 1 and calls[0][2] == [] and calls[0][3].max_iterations == 1
    assert "untrusted data" in calls[0][0]
    assert "app.py" in {item["path"] for item in calls[0][1]["source_prefixes"]}
    metadata = enabled.last_repair
    assert metadata["original_answer"] == ORIGINAL
    assert metadata["final_answer"] == CORRECTED
    assert metadata["before"] == {"total": 2, "valid": 1, "invalid": 1}
    assert metadata["after"] == {"total": 2, "valid": 2, "invalid": 0}
    assert metadata["attempted"] and metadata["accepted"]
    metadata["original_answer"] = "mutated external copy"
    metadata["before"]["invalid"] = 0
    assert enabled.last_repair["original_answer"] == ORIGINAL
    assert enabled.last_repair["before"]["invalid"] == 1
    with pytest.raises(FrozenInstanceError):
        enabled._last_repair.original_answer = "changed"


@pytest.mark.parametrize("proposal", [
    "", "a rewritten factual answer", '{"edits":[]}',
    plan(replacement="`missing.py:1`"),
    plan(replacement="New claim `app.py:1`"),
    plan(source="`app.py:3`", replacement=""),
    json.dumps({"edits": [{"citation": "`app.py:999`", "replacement": "`app.py:1`"}],
                "answer": "Changed facts"}),
])
def test_empty_worse_and_unrestricted_rewrites_keep_the_original(project, proposal):
    result = citation_repair.repair_answer(
        ORIGINAL, project.root, Settings(), invoke=lambda *a, **kw: proposal
    )
    assert result.attempted and not result.accepted
    assert result.selected_answer == ORIGINAL
    assert result.initial_report.metrics()["invalid"] == 1


def test_removing_all_evidence_is_not_an_improvement(project):
    answer = "L'API est décrite dans `app.py:999`."
    result = citation_repair.repair_answer(
        answer, project.root, Settings(), invoke=lambda *a, **kw: plan(replacement="")
    )
    assert result.candidate_answer == "L'API est décrite dans ."
    assert not result.accepted and result.selected_answer == answer


def test_only_unsupported_reference_can_be_removed_when_valid_evidence_remains(project):
    result = citation_repair.repair_answer(
        ORIGINAL, project.root, Settings(), invoke=lambda *a, **kw: plan(replacement="")
    )
    assert result.accepted
    assert result.selected_answer == ORIGINAL.replace("`app.py:999`", "")
    assert result.selected_report.metrics() == {"total": 1, "valid": 1, "invalid": 0}


def test_editing_short_reference_never_changes_a_valid_longer_path(project):
    folder = project.root / "nested"
    folder.mkdir()
    (folder / "missing.py").write_text("a = 1\n")
    answer = "Une source missing.py:1 et une autre nested/missing.py:1."
    result = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: plan("missing.py:1", "app.py:1"),
    )
    assert result.accepted
    assert result.selected_answer == "Une source app.py:1 et une autre nested/missing.py:1."


def test_failure_keeps_the_original_and_does_not_retry(project):
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("temporary model failure")

    result = citation_repair.repair_answer(ORIGINAL, project.root, Settings(), invoke=unavailable)
    assert len(calls) == 1 and result.reason == "repair_failed"
    assert result.selected_answer == ORIGINAL
    assert result.initial_report.metrics() == result.selected_report.metrics()


def test_single_sdk_iteration_has_no_tools_and_retains_usage_hook(project, monkeypatch):
    calls, usage = [], []

    class Messages:
        def tool_runner(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text=plan())]
            )
            return iter([message])

    client = SimpleNamespace(api_key="synthetic", auth_token=None, credentials=None,
                             beta=SimpleNamespace(messages=Messages()))
    monkeypatch.setattr(runner.anthropic, "Anthropic", lambda: client)
    result = citation_repair.repair_answer(
        ORIGINAL, project.root, Settings(max_iterations=40),
        call_options={"on_usage": usage.append, "on_text": lambda text: pytest.fail(text)},
    )
    assert result.accepted and len(calls) == 1
    assert calls[0]["max_iterations"] == 1 and calls[0]["tools"] == []
    assert "stream" not in calls[0]
    assert len(usage) == 1


def test_shared_limiter_is_forwarded_but_streaming_callbacks_are_not(project):
    marker = object()
    forwarded = []

    def call(*args, **options):
        forwarded.append(options)
        return plan()

    citation_repair.repair_answer(
        ORIGINAL, project.root, Settings(), invoke=call,
        call_options={"limits": marker, "on_text": "do not forward", "on_tool": "no tools"},
    )
    assert forwarded == [{"limits": marker}]


def test_enabled_streaming_emits_only_the_final_verified_answer(project, monkeypatch):
    received, initial_options = [], []

    def initial(*args, **options):
        initial_options.append(options)
        return ORIGINAL

    monkeypatch.setattr(features, "run_agent", initial)
    monkeypatch.setattr(citation_repair, "run_agent", lambda *a, **kw: plan())
    enabled = session(project, repair_citations=True, on_text=received.append)
    answer = features.ask(enabled, "Comment ?")
    assert "on_text" not in initial_options[0]
    assert received == [answer] and answer.startswith(CORRECTED)
    assert ORIGINAL not in received[0]


def test_overview_preserves_real_diagram_and_the_original_report(project, monkeypatch):
    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: ORIGINAL)
    monkeypatch.setattr(citation_repair, "run_agent", lambda *a, **kw: plan())
    enabled = session(project, repair_citations=True)
    answer = features.overview(enabled)
    assert answer.startswith(CORRECTED)
    initial = list(enabled.store.dir.glob("overview-initial-*.md"))
    assert len(initial) == 1 and initial[0].read_text().startswith(ORIGINAL)
    assert (enabled.store.dir / "overview.md").read_text() == answer
    if "```mermaid" in enabled.last_repair["original_answer"]:
        original_graph = enabled.last_repair["original_answer"].split("```mermaid", 1)[1]
        selected_graph = enabled.last_repair["final_answer"].split("```mermaid", 1)[1]
        assert original_graph == selected_graph


def test_structured_decisions_are_never_repaired_and_clear_prior_metadata(project, monkeypatch):
    enabled = session(project, repair_citations=True)
    monkeypatch.setattr(features, "run_agent", lambda *a, **kw: ORIGINAL)
    monkeypatch.setattr(citation_repair, "run_agent", lambda *a, **kw: plan())
    features.ask(enabled, "Comment ?")
    assert enabled.last_repair is not None
    record = Decision(
        title="FastAPI", category="framework", context="ctx", decision="Use FastAPI",
        rationale="inferred", rationale_source="inferred", consequences=[],
        evidence=["`missing.py:1`"],
    )

    def structured(system, task, tools, settings, on_tool=None):
        next(tool for tool in tools if getattr(tool, "name", "") == "record_decision").call(
            record.model_dump()
        )
        return "Synthèse."

    monkeypatch.setattr(features, "run_agent", structured)
    monkeypatch.setattr(
        citation_repair, "run_agent", lambda *a, **kw: pytest.fail("unexpected structured repair")
    )
    features.decisions(enabled)
    assert enabled.store.load_decisions() == [record]
    assert enabled.last_repair is None


def test_payload_limits_and_ignored_sources(project):
    seen = []

    def call(system, task, *args, **kwargs):
        seen.append(json.loads(task))
        return '{"edits":[]}'

    result = citation_repair.repair_answer(
        "Secret `.env:1` and `app.py:999`.", project.root, Settings(), invoke=call
    )
    assert result.attempted and seen
    assert "sk_live_secret" not in json.dumps(seen)
    assert ".env" not in {item["path"] for item in seen[0]["source_prefixes"]}
    oversized = citation_repair.repair_answer(
        ORIGINAL + "x" * citation_repair.MAX_ANSWER_CHARS, project.root, Settings(),
        invoke=lambda *a, **kw: pytest.fail("oversized payload should not be sent"),
    )
    assert not oversized.attempted and oversized.reason == "input_limit"


def test_pathological_line_number_remains_invalid_without_losing_the_answer(project):
    answer = f"Citation `app.py:{'9' * 5000}`."
    report = evidence.verify(answer, project.root)
    assert len(report.problems) == 1
    result = citation_repair.repair_answer(
        answer, project.root, Settings(), invoke=lambda *args, **kwargs: '{"edits":[]}'
    )
    assert result.selected_answer == answer and not result.accepted
