import json

import httpx2
import pytest
from typer.testing import CliRunner

from learn_it import chat, cli, features
from learn_it.agent.limits import SessionLimitError
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store


@pytest.mark.parametrize("command,args", [
    ("ask", ["Question"]), ("overview", []), ("why", ["app.py"]),
    ("decisions", []), ("review", []),
])
def test_every_ai_command_forwards_local_limits(project, monkeypatch, command, args):
    seen = []

    def fake(session, *arguments, **options):
        seen.append(session)
        assert session.settings.max_requests == 2
        assert session.settings.max_output_tokens == 512
        if session.on_text is not None:
            session.on_text("FINAL_LIMITED_ANSWER")
        return "FINAL_LIMITED_ANSWER"

    monkeypatch.setattr(features, command, fake)
    result = CliRunner().invoke(cli.app, [
        command, *args, "-p", str(project.root), "--max-requests", "2",
        "--max-output-tokens", "512",
    ])
    assert result.exit_code == 0, result.output
    assert len(seen) == 1
    assert result.stdout.count("FINAL_LIMITED_ANSWER") == 1


def test_chat_receives_one_session_limit_for_the_whole_conversation(project, monkeypatch):
    sessions = []
    monkeypatch.setattr(chat, "interactive", sessions.append)
    result = CliRunner().invoke(cli.app, [
        "chat", "-p", str(project.root), "--max-requests", "3", "--max-output-tokens", "256",
    ])
    assert result.exit_code == 0, result.output
    assert sessions[0].settings.max_requests == 3
    assert sessions[0].settings.max_output_tokens == 256


@pytest.mark.parametrize("stream", [True, False])
def test_opt_in_repair_buffers_the_answer_and_prints_it_once(project, monkeypatch, stream):
    def fake(session, question):
        assert session.repair_citations
        assert session.on_text is None
        return "ONLY_THE_SELECTED_ANSWER"

    monkeypatch.setattr(features, "ask", fake)
    result = CliRunner().invoke(cli.app, [
        "ask", "Question", "-p", str(project.root), "--repair-citations",
        "--stream" if stream else "--no-stream",
    ])
    assert result.exit_code == 0, result.output
    assert result.stdout.count("ONLY_THE_SELECTED_ANSWER") == 1


def test_chat_can_save_and_exit_after_quota_exhaustion(project, monkeypatch, capsys):
    closed, attempts = [], []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.transcript = []

        def ask(self, question, *, on_text, **kwargs):
            attempts.append(question)
            if len(attempts) > 1:
                raise SessionLimitError(1)
            self.transcript += [("Vous", question), ("Claude", "Voir `app.py:1`.")]
            on_text("Voir `app.py:1`.")
            return "Voir `app.py:1`."

        def markdown(self):
            return "\n".join(text for role, text in self.transcript)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(chat, "ConversationAgent", FakeAgent)
    session = Session(project, scan(project), Store(project.root), Settings(max_requests=1))
    questions = iter(["Première", "Quota épuisé", "/save", "/exit"])
    chat.interactive(session, read=lambda: next(questions))
    transcript = next(session.store.dir.glob("chat-*.md")).read_text()
    assert "Première" in transcript
    assert "Quota épuisé" not in transcript  # preflight did not stage a new turn
    assert "/save reste disponible" in capsys.readouterr().err
    assert closed == [True]


@pytest.mark.parametrize("cap,expected_requests,accepted", [(1, 1, False), (2, 2, True)])
def test_initial_answer_and_citation_repair_share_the_actual_request_guard(
    project, monkeypatch, cap, expected_requests, accepted
):
    from tests.test_session_limits import client_factory, reply

    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            text = "Voir `app.py:1` et `./missing.py:9`."
        else:
            text = json.dumps({"edits": [
                {"citation": "`./missing.py:9`", "replacement": "`app.py:3`"}
            ]})
        return httpx2.Response(200, json=reply(len(requests), text=text))

    client_factory(monkeypatch, handler)
    session = Session(
        project, scan(project), Store(project.root), Settings(max_requests=cap),
        repair_citations=True,
    )
    answer = features.ask(session, "Question")
    assert len(requests) == session.limits.requests_sent == expected_requests
    assert session.last_repair["accepted"] is accepted
    if cap == 1:
        assert session.last_repair["reason"] == "request_limit"
    assert ("`./missing.py:9`" in answer) is (not accepted)
