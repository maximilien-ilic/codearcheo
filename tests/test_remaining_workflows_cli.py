import pytest
from typer.testing import CliRunner

from learn_it import chat, cli, features


@pytest.mark.parametrize("command,args", [
    ("ask", ["Question"]), ("overview", []), ("why", ["app.py"]),
    ("decisions", []), ("review", []),
])
def test_every_ai_command_forwards_local_limits(project, monkeypatch, command, args):
    seen = []

    def fake(session, *arguments):
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
