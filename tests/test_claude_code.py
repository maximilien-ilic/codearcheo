"""The claude-code backend, against a fake `claude` executable: no subscription used."""

import json
import os
import stat
import sys

import pytest

from learn_it import features
from learn_it.agent.limits import AgentError
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store

FAKE = """#!{python}
import json, os, sys
with open(os.environ["FAKE_CLAUDE_LOG"], "w") as log:
    argv = sys.argv[1:]
    mcp = json.load(open(argv[argv.index("--mcp-config") + 1]))
    json.dump({{"argv": argv, "mcp": mcp, "api_key": "ANTHROPIC_API_KEY" in os.environ}}, log)
print(os.environ["FAKE_CLAUDE_OUTPUT"])
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "claude"
    executable.write_text(FAKE.format(python=sys.executable))
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "call.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-reach-claude")

    def reply(**result):
        result = {"type": "result", "is_error": False, "num_turns": 3, "total_cost_usd": 0.12,
                  "usage": {"input_tokens": 10, "output_tokens": 20}, **result}
        monkeypatch.setenv("FAKE_CLAUDE_OUTPUT", json.dumps(result))
        return lambda: json.loads((tmp_path / "call.json").read_text())

    return reply


def session(project, **options):
    settings = Settings(backend="claude-code", **options)
    return Session(project, scan(project), Store(project.root), settings, on_usage=lambda u: None)


def test_ask_runs_on_the_subscription_with_learn_it_tools_only(project, fake_claude):
    call = fake_claude(result="FastAPI depuis `app.py:3`.")

    answer = features.ask(session(project), "Quel framework ?")

    assert answer.startswith("FastAPI depuis `app.py:3`.")
    logged = call()
    argv = logged["argv"]
    assert not logged["api_key"]  # the subscription, not API credits
    assert argv[argv.index("--tools") + 1] == ""  # no built-in tools
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__learn-it"
    server = logged["mcp"]["mcpServers"]["learn-it"]
    assert server["args"] == ["-m", "learn_it", "serve", "-p", str(project.root)]
    assert "<project_profile>" in argv[argv.index("--system-prompt") + 1]


def test_decisions_come_back_as_structured_output_and_are_validated(project, fake_claude):
    good = {
        "title": "FastAPI pour l'API", "category": "framework", "context": "…",
        "decision": "Remplacer Flask par FastAPI.", "rationale": "Le commit le dit.",
        "rationale_source": "documented", "consequences": ["async"],
        "evidence": ["`app.py:3` crée l'application"],
    }
    call = fake_claude(structured_output={
        "synthesis": "Une API FastAPI.", "record_decision": [good, {"title": "incomplet"}],
    })
    current = session(project)

    report = features.decisions(current)

    assert [d.title for d in current.store.load_decisions()] == ["FastAPI pour l'API"]
    assert "Une API FastAPI." in report
    schema = json.loads(call()["argv"][call()["argv"].index("--json-schema") + 1])
    assert schema["required"] == ["synthesis", "record_decision"]


def test_failures_and_unsupported_options_are_explicit(project, fake_claude):
    fake_claude(is_error=True, result="quota atteint")
    with pytest.raises(AgentError, match="quota atteint"):
        features.ask(session(project), "?")
    with pytest.raises(AgentError, match="max-requests"):
        features.ask(session(project, max_requests=3), "?")
    repaired = session(project)
    repaired.repair_citations = True
    with pytest.raises(AgentError, match="repair-citations"):
        features.ask(repaired, "?")


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="LEARN_IT_BACKEND"):
        Settings(backend="gemini")
