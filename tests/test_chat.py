import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from learn_it import chat
from learn_it.agent import runner
from learn_it.agent.runner import ConversationAgent, run_agent
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store


def response(number, text="Answer", *, content=None, reason="end_turn", inputs=10):
    return {
        "id": f"msg_{number}",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content or [{"type": "text", "text": text}],
        "stop_reason": reason,
        "stop_sequence": None,
        "usage": {"input_tokens": inputs, "output_tokens": 5},
    }


def mocked_client(monkeypatch, handler):
    client = anthropic.Anthropic(
        api_key="sk-test-not-real",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(runner, "_client", lambda: client)
    return client


def test_follow_up_uses_same_sdk_thread_with_prior_tool_results(monkeypatch):
    requests = []
    lookups = []

    def lookup(name: str) -> str:
        """Look up the stored fact for a given name."""
        lookups.append(name)
        return "Redis owns the sessions"

    replies = [
        response(
            1,
            content=[
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "lookup",
                    "input": {"name": "sessions"},
                }
            ],
            reason="tool_use",
        ),
        response(2, "Redis owns the sessions"),
        response(3, "As above, Redis owns the sessions"),
    ]

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(requests) - 1])

    mocked_client(monkeypatch, handler)
    agent = ConversationAgent("system", [lookup], Settings())
    try:
        assert agent.ask("Who owns sessions?") == "Redis owns the sessions"
        history = json.dumps(list(agent.thread.messages), default=lambda obj: obj.model_dump())
        assert "tool_result" in history
        assert "Redis owns the sessions" in history
        assert agent.ask("And where does that live?") == "As above, Redis owns the sessions"
        assert requests[2]["thread"] == {"type": "continue", "previous_message_id": "msg_2"}
        assert len(requests[2]["messages"]) == 1
        assert lookups == ["sessions"]
        assert "Who owns sessions?" in agent.markdown()
        assert "And where does that live?" in agent.markdown()
    finally:
        agent.close()


def stream_response(message, chunks):
    start = {
        **message,
        "content": [],
        "stop_reason": None,
        "usage": {"input_tokens": 10, "output_tokens": 0},
    }
    events = [
        {"type": "message_start", "message": start},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        *[
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": chunk},
            }
            for chunk in chunks
        ],
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})


def test_streaming_delivers_chunks_and_still_returns_final_answer_and_usage(monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return stream_response(response(1, "Hello world"), ["Hello ", "world"])

    mocked_client(monkeypatch, handler)
    chunks, usages = [], []
    answer = run_agent(
        "system", "task", [], Settings(budget=30_000), on_text=chunks.append, on_usage=usages.append
    )
    assert chunks == ["Hello ", "world"]
    assert answer == "Hello world"
    assert requests[0]["stream"] is True
    assert requests[0]["output_config"]["task_budget"]["total"] == 30_000
    assert usages[0].input_tokens == 10
    assert usages[0].output_tokens == 5
    assert usages[0].requests == 1


def test_long_conversation_compacts_after_answer_and_keeps_follow_up(monkeypatch):
    requests = []
    replies = [
        response(1, "Original answer", inputs=150),
        response(
            2,
            content=[{"type": "compaction", "content": "Previous question and answer"}],
            reason="compaction",
        ),
        response(3, "Follow-up answer"),
    ]

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(requests) - 1])

    mocked_client(monkeypatch, handler)
    agent = ConversationAgent("system", [], Settings(compact_threshold=100))
    try:
        assert agent.ask("First question") == "Original answer"
        assert requests[1]["compaction"] == {"type": "summarize"}
        assert list(agent.thread.messages)[0]["content"][0].type == "compaction"
        assert agent.ask("Follow-up question") == "Follow-up answer"
        history = json.dumps(list(agent.thread.messages), default=lambda obj: obj.model_dump())
        assert "Previous question and answer" in history
        assert "Follow-up question" in history
        assert "Original answer" in agent.markdown()  # /save retains the unabridged dialogue
    finally:
        agent.close()


def test_interactive_chat_saves_full_transcript_and_closes(project, monkeypatch):
    closed = []

    class FakeAgent:
        def __init__(self, *args):
            self.answers = []

        def ask(self, question, *, on_text, **kwargs):
            self.answers.append(question)
            on_text("Reply")

        def markdown(self):
            return "# Conversation\n" + "\n".join(self.answers)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(chat, "ConversationAgent", FakeAgent)
    session = Session(project, scan(project), Store(project.root), Settings())
    questions = iter(["First", "Second", "/save", "/exit"])
    chat.interactive(session, read=lambda: next(questions))
    saved = list(session.store.dir.glob("chat-*.md"))
    assert len(saved) == 1
    assert "First\nSecond" in saved[0].read_text()
    assert closed == [True]


def test_interrupted_stream_reports_usage_as_incomplete_and_closes(monkeypatch):
    closed = []

    class BrokenRunner:
        def __iter__(self):
            raise OSError("connection interrupted")

        def close(self):
            closed.append(True)

    client = SimpleNamespace(
        api_key="fake",
        auth_token=None,
        credentials=None,
        beta=SimpleNamespace(messages=SimpleNamespace(tool_runner=lambda **kwargs: BrokenRunner())),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(runner, "_client", lambda: client)
    usage = []
    with pytest.raises(OSError):
        run_agent("system", "task", [], Settings(), on_usage=usage.append)
    assert usage[0].missing_usage
    assert usage[0].estimated_cost_usd is None
    assert closed == [True, True]
