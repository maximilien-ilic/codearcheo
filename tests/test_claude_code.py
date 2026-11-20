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
path = os.environ["FAKE_CLAUDE_LOG"]
calls = json.load(open(path)) if os.path.exists(path) else []
argv = sys.argv[1:]
mcp = json.load(open(argv[argv.index("--mcp-config") + 1]))
calls.append({{"argv": argv, "mcp": mcp, "api_key": "ANTHROPIC_API_KEY" in os.environ}})
json.dump(calls, open(path, "w"))
outputs = json.loads(os.environ["FAKE_CLAUDE_OUTPUT"])
print(json.dumps(outputs[min(len(calls), len(outputs)) - 1]))
"""


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    monkeypatch.setattr("learn_it.agent.claude_code.find_spec", lambda _: object())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "claude"
    executable.write_text(FAKE.format(python=sys.executable))
    executable.chmod(executable.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "call.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-reach-claude")

    def reply(*then, **result):
        """One reply per call, in order; the last one repeats. The log returns the last call."""
        outputs = [{"type": "result", "is_error": False, "num_turns": 3, "total_cost_usd": 0.12,
                    "usage": {"input_tokens": 10, "output_tokens": 20}, **item}
                   for item in (result, *then)]
        monkeypatch.setenv("FAKE_CLAUDE_OUTPUT", json.dumps(outputs))
        return lambda: json.loads((tmp_path / "call.json").read_text())[-1]

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
    assert argv[argv.index("--max-turns") + 1] == str(Settings.max_iterations)
    assert argv[argv.index("--allowedTools") + 1] == "mcp__learn-it"
    server = logged["mcp"]["mcpServers"]["learn-it"]
    assert server["args"][:5] == ["-m", "learn_it", "serve", "-p", str(project.root)]
    assert server["args"][5] == "--profile-file"  # the profile just computed, not a rescan
    assert "<project_profile>" in argv[argv.index("--system-prompt") + 1]


@pytest.mark.parametrize("max_iterations", [1, 7])
def test_custom_iteration_limit_reaches_claude(project, fake_claude, monkeypatch, max_iterations):
    call = fake_claude(result="FastAPI depuis `app.py:3`.")
    monkeypatch.setenv("LEARN_IT_MAX_ITERATIONS", str(max_iterations))
    current = session(project)
    current.settings = Settings.from_env(backend="claude-code")

    features.ask(current, "Quel framework ?")

    argv = call()["argv"]
    assert argv[argv.index("--max-turns") + 1] == str(max_iterations)


def test_turn_limit_reports_usage_and_stops_without_final_records(project, fake_claude):
    fake_claude(is_error=True, subtype="error_max_turns", num_turns=3)
    current = session(project, max_iterations=3)
    usages = []
    current.on_usage = usages.append

    with pytest.raises(AgentError, match="3 tours.*LEARN_IT_MAX_ITERATIONS"):
        features.decisions(current)

    assert len(usages) == 1
    assert usages[0].requests == 3
    assert usages[0].estimated_cost_usd == 0.12
    assert current.store.load_decisions() == []


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
    with pytest.raises(AgentError, match="max-output-tokens"):
        features.ask(session(project, max_output_tokens=20), "?")


def test_citation_repair_is_one_tool_free_request_on_the_subscription(
    project, fake_claude, tmp_path,
):
    edit = {"edits": [{"citation": "`./apps.py:3`", "replacement": "`app.py:3`"}]}
    call = fake_claude({"result": json.dumps(edit), "num_turns": 1},
                       result="FastAPI depuis `./apps.py:3`.")
    current = session(project)
    current.repair_citations = True

    answer = features.ask(current, "Quel framework ?")

    assert answer.startswith("FastAPI depuis `app.py:3`.")
    assert current.last_repair["accepted"]
    calls = json.loads((tmp_path / "call.json").read_text())
    assert len(calls) == 2
    argv = call()["argv"]
    assert call()["mcp"] == {"mcpServers": {}}  # neither project tools nor built-in ones
    assert argv[argv.index("--tools") + 1] == ""
    assert "--allowedTools" not in argv
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--system-prompt") + 1].startswith("Repair source references")
    assert not call()["api_key"]


def test_rejected_repair_keeps_the_initial_answer(project, fake_claude):
    fake_claude({"result": "Voici la correction : `app.py:3`", "num_turns": 1},
                result="FastAPI depuis `./apps.py:3`.")
    current = session(project)
    current.repair_citations = True

    answer = features.ask(current, "Quel framework ?")

    assert answer.startswith("FastAPI depuis `./apps.py:3`.")
    assert current.last_repair["reason"] == "repair_failed"
    assert "réponse initiale conservée" in answer


def test_no_repair_request_when_every_citation_is_valid(project, fake_claude, tmp_path):
    fake_claude(result="FastAPI depuis `app.py:3`.")
    current = session(project)
    current.repair_citations = True

    features.ask(current, "Quel framework ?")

    assert len(json.loads((tmp_path / "call.json").read_text())) == 1


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="LEARN_IT_BACKEND"):
        Settings(backend="gemini")


def test_output_limit_is_rejected_even_when_it_matches_the_default(monkeypatch):
    with pytest.raises(ValueError, match="max-output-tokens"):
        Settings.from_env(backend="claude-code", max_output_tokens=Settings.max_output_tokens)
    monkeypatch.setenv("LEARN_IT_MAX_OUTPUT_TOKENS", "20")
    with pytest.raises(ValueError, match="max-output-tokens"):
        Settings.from_env(backend="claude-code")


def test_missing_mcp_extra_is_reported_before_running_claude(project, fake_claude, monkeypatch):
    monkeypatch.setattr("learn_it.agent.claude_code.find_spec", lambda _: None)
    with pytest.raises(AgentError, match="extra mcp"):
        features.ask(session(project), "?")


def test_structured_tasks_ask_for_the_answer_only_once(project, fake_claude):
    call = fake_claude(structured_output={"synthesis": "Rien.", "record_decision": []})

    with pytest.raises(AgentError):  # no record: only the request matters here
        features.decisions(session(project))

    argv = call()["argv"]
    assert "do not write the answer as text first" in argv[argv.index("-p") + 1]


def test_the_profile_reaches_the_model_as_compact_json(project):
    from learn_it.agent import prompts

    system = prompts.system(scan(project))
    profile = system.split("<project_profile>\n", 1)[1].split("\n</project_profile>", 1)[0]
    assert "\n" not in profile and ": null" not in profile and json.loads(profile)["files"]


@pytest.mark.parametrize("terminal", [True, False])
def test_a_waiting_indicator_shows_in_a_terminal_only(project, fake_claude, monkeypatch, terminal):
    import io

    from rich.console import Console

    from learn_it import render

    stream = io.StringIO()
    monkeypatch.setattr(render, "err", Console(file=stream, force_terminal=terminal, width=80))
    fake_claude(result="FastAPI depuis `app.py:3`.")

    answer = features.ask(session(project), "Quel framework ?")

    assert answer.startswith("FastAPI depuis `app.py:3`.")
    assert ("Claude Code explore le projet" in stream.getvalue()) is terminal
