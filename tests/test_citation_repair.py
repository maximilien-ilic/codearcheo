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
    answer = "Une source ./missing.py:1 et une autre nested/missing.py:1."
    result = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: plan("./missing.py:1", "app.py:1"),
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
    client.with_options = lambda **options: client
    client.with_middleware = lambda *middleware: client
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
    assert forwarded == [{"limits": marker, "single_request": True}]


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


@pytest.mark.parametrize("opening,closing", [
    ("```mermaid", "```"), ("```python", "```"), ("~~~python", "~~~"),
    ("```mermaid", ""), ("~~~", ""), ("````markdown", "````"),
    ("> ```mermaid", "> ```"), ("- ```python", "  ```"),
])
def test_fenced_examples_and_diagrams_never_become_editable_citations(project, opening, closing):
    diagram = f'{opening}\nx["lost.py:99"]\n{closing}'
    answer = f"Source valide `app.py:3`.\n\n{diagram}"
    result = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: pytest.fail("code examples must not trigger citation repair"),
    )
    assert not result.attempted
    assert result.selected_answer == answer
    assert result.initial_report.metrics() == {"total": 1, "valid": 1, "invalid": 0}


def test_an_edit_cannot_touch_the_same_reference_inside_a_complete_fence(project):
    diagram = '```mermaid\nx["./lost.py:99"]\n```'
    answer = f"Source `app.py:3` ; autre source ./lost.py:99.\n\n{diagram}"
    result = citation_repair.repair_answer(
        answer, project.root, Settings(), invoke=lambda *a, **kw: plan("./lost.py:99", "app.py:1")
    )
    assert result.accepted
    expected = answer.replace("autre source ./lost.py:99", "autre source app.py:1")
    assert result.selected_answer == expected
    assert diagram in result.selected_answer


def test_original_valid_evidence_cannot_be_lost_while_the_model_is_waiting(project):
    root = project.root
    (root / "good.py").write_text("first = 1\nsecond = 2\n")
    (root / "a.py").write_text("a = 1\n")
    (root / "b.py").write_text("b = 1\n")
    answer = "Source `good.py:2` ; références `a.py:99` et `b.py:99`."

    def changes_during_request(*args, **kwargs):
        (root / "good.py").write_text("first = 1\n")
        return json.dumps({"edits": [
            {"citation": "`a.py:99`", "replacement": "`a.py:1`"},
            {"citation": "`b.py:99`", "replacement": "`b.py:1`"},
        ]})

    result = citation_repair.repair_answer(
        answer, root, Settings(), invoke=changes_during_request
    )
    assert result.attempted and not result.accepted
    assert result.selected_answer == answer
    assert result.initial_report.metrics() == {"total": 3, "valid": 1, "invalid": 2}
    assert result.candidate_report.metrics() == {"total": 3, "valid": 2, "invalid": 1}


@pytest.mark.parametrize("endpoint", [
    "127.0.0.1:8000", "api.example.com:443", "server.local:9000", "localhost:8080",
    "https://api.example.com:443/v1", "http://127.0.0.1:8000/api",
])
@pytest.mark.parametrize("quoted", [False, True])
def test_network_values_are_not_citations_or_edit_targets(project, endpoint, quoted):
    value = f"`{endpoint}`" if quoted else endpoint
    answer = f"Server listens on {value}; source `app.py:3`."
    result = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: pytest.fail("network values must not trigger citation repair"),
    )
    assert not result.attempted
    assert result.selected_answer == answer
    assert result.initial_report.metrics() == {"total": 1, "valid": 1, "invalid": 0}


@pytest.mark.parametrize("endpoint", ["127.0.0.1:8000", "api.example.com:443"])
@pytest.mark.parametrize("quoted", [False, True])
def test_real_citation_repair_cannot_change_network_values(project, endpoint, quoted):
    value = f"`{endpoint}`" if quoted else endpoint
    answer = f"Server listens on {value}; source `app.py:3`; bad `app.py:999`."
    repaired = citation_repair.repair_answer(
        answer, project.root, Settings(), invoke=lambda *a, **kw: plan()
    )
    assert repaired.accepted
    assert repaired.selected_answer == answer.replace("`app.py:999`", "`app.py:1-3`")
    rejected = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: plan(value, "`app.py:1`"),
    )
    assert not rejected.accepted
    assert rejected.selected_answer == answer


@pytest.mark.parametrize("reference", [
    "server.go:8080", "`server.go:8080`", "missing.py:9", "`missing.py:9`",
])
def test_unknown_standalone_source_shaped_names_are_warned_but_never_guessed(project, reference):
    answer = f"Reference {reference}; valid source `app.py:3`."
    result = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: pytest.fail("ambiguous names must not trigger an API request"),
    )
    assert result.selected_answer == answer
    assert result.reason == "ambiguous_reference" and not result.attempted
    assert result.initial_report.metrics() == {"total": 2, "valid": 1, "invalid": 1}


def test_an_eligible_edit_does_not_authorize_editing_an_ambiguous_network_value(project):
    answer = "Server at `server.go:8080`; source `app.py:3`; bad `app.py:999`."
    captured = []

    def edit_only_sources(system, task, *args, **kwargs):
        captured.append(json.loads(task)["invalid_references"])
        return plan()

    accepted = citation_repair.repair_answer(
        answer, project.root, Settings(), invoke=edit_only_sources
    )
    assert accepted.accepted
    assert "`server.go:8080`" in accepted.selected_answer
    assert [item["citation"] for item in captured[0]] == ["`app.py:999`"]
    rejected = citation_repair.repair_answer(
        answer, project.root, Settings(),
        invoke=lambda *a, **kw: plan("`server.go:8080`", "`app.py:1`"),
    )
    assert not rejected.accepted and rejected.selected_answer == answer
