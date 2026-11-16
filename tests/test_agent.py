from types import SimpleNamespace

import pytest
from anthropic.lib.tools import ToolError

from learn_it import features
from learn_it.agent import runner
from learn_it.agent.runner import AgentError, run_agent
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store


def reply(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


def text(value):
    return SimpleNamespace(type="text", text=value)


def tool_use(name, **arguments):
    return SimpleNamespace(type="tool_use", name=name, input=arguments)


@pytest.fixture
def fake_claude(monkeypatch):
    """Swap the Anthropic client for one whose tool runner yields scripted replies."""
    params = {}

    def script(*replies):
        class Messages:
            def tool_runner(self, **kwargs):
                params.update(kwargs)
                return iter(replies)

        client = SimpleNamespace(
            api_key="sk-test", auth_token=None, credentials=None,
            beta=SimpleNamespace(messages=Messages()),
        )
        monkeypatch.setattr(runner.anthropic, "Anthropic", lambda: client)
        return params

    return script


def test_run_agent_explains_missing_credentials(monkeypatch, tmp_path):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE",
                "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_IDENTITY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no `ant auth login` profile either
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(AgentError, match="ANTHROPIC_API_KEY"):
        run_agent("system", "task", [], Settings())


def test_run_agent_reports_tool_calls_and_returns_the_answer(fake_claude):
    params = fake_claude(
        reply("tool_use", tool_use("search_code", regex="redis")),
        reply("end_turn", text("Redis caches sessions (`app.py:3`).")),
    )
    seen = []

    answer = run_agent("system", "task", [], Settings(), on_tool=lambda *call: seen.append(call))

    assert answer == "Redis caches sessions (`app.py:3`)."
    assert seen == [("search_code", {"regex": "redis"})]
    assert params["model"] == "claude-opus-5-5"
    assert params["fallbacks"] == "default"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize("stop_reason", ["refusal", "tool_use"])
def test_run_agent_fails_loudly_without_a_final_answer(fake_claude, stop_reason):
    fake_claude(reply(stop_reason, text("partial")))
    with pytest.raises(AgentError):
        run_agent("system", "task", [], Settings())


def test_decisions_are_recorded_then_saved(project, monkeypatch):
    record = {
        "title": "FastAPI for the HTTP layer",
        "category": "framework",
        "context": "The checkout needed async endpoints.",
        "decision": "Replace Flask with FastAPI.",
        "rationale": "The commit says so: 'for async support'.",
        "rationale_source": "documented",
        "consequences": ["Endpoints are async."],
        "evidence": ["commit abc1234: Switch from Flask to FastAPI for async support"],
    }

    def fake_run_agent(system, task, tools, settings, on_tool=None):
        record_decision = next(t for t in tools if getattr(t, "name", "") == "record_decision")
        schema = record_decision.to_dict()["input_schema"]
        assert schema["properties"]["rationale_source"]["enum"] == ["documented", "inferred"]
        record_decision.call(record)
        with pytest.raises(ToolError):
            record_decision.call({"title": "missing every other field"})
        return "FastAPI is the backbone."

    monkeypatch.setattr(features, "run_agent", fake_run_agent)
    store = Store(project.root)

    report = features.decisions(Session(project, scan(project), store, Settings()))

    assert [d.title for d in store.load_decisions()] == ["FastAPI for the HTTP layer"]
    assert "## 1. FastAPI for the HTTP layer" in report
    assert (store.dir / "decisions.md").read_text() == report
