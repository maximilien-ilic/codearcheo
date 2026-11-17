"""Exercise pre-send caps through the installed SDK and a local HTTP/SSE transport."""

import json

import anthropic
import httpx2
import pytest

from learn_it.agent import runner
from learn_it.agent.limits import AgentError, SessionLimitError, SessionLimits
from learn_it.agent.runner import ConversationAgent, run_agent
from learn_it.config import Settings


def reply(number=1, *, text="Answer", reason="end_turn", content=None, inputs=10):
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


def sse(message):
    start = {
        **message,
        "content": [],
        "stop_reason": None,
        "usage": {"input_tokens": message["usage"]["input_tokens"], "output_tokens": 0},
    }
    events = [{"type": "message_start", "message": start}]
    for index, block in enumerate(message["content"]):
        initial = {**block, "text": ""} if block["type"] == "text" else block
        events.append({"type": "content_block_start", "index": index, "content_block": initial})
        if block["type"] == "text":
            events.append(
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": block["text"]},
                }
            )
        events.append({"type": "content_block_stop", "index": index})
    events += [
        {
            "type": "message_delta",
            "delta": {"stop_reason": message["stop_reason"]},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})


def client_factory(monkeypatch, handler, *, retries=0, follow_redirects=False):
    created = []

    def create():
        client = anthropic.Anthropic(
            api_key="synthetic-key-no-network",
            max_retries=retries,
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler), follow_redirects=follow_redirects
            ),
        )
        created.append(client)
        return client

    monkeypatch.setattr(runner, "_client", create)
    return created


def test_generation_redirect_cannot_bypass_request_cap(monkeypatch):
    forwarded = []

    def handler(request):
        forwarded.append(request)
        if len(forwarded) == 1:
            return httpx2.Response(
                307, headers={"location": "https://api.anthropic.com/v1/messages?redirected=1"}
            )
        return httpx2.Response(200, json=reply())

    client_factory(monkeypatch, handler, follow_redirects=True)
    limits = SessionLimits(max_requests=1)
    with pytest.raises(anthropic.APIStatusError) as error:
        run_agent("system", "task", [], Settings(), limits=limits)
    assert error.value.status_code == 307
    assert len(forwarded) == limits.requests_sent == 1


def test_single_request_mode_disables_retries_without_resetting_shared_limits(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(500, json={"error": {"type": "api_error", "message": "synthetic"}})

    client_factory(monkeypatch, handler, retries=2)
    shared = SessionLimits(max_requests=5)
    with pytest.raises(anthropic.APIStatusError):
        run_agent("system", "task", [], Settings(), limits=shared, single_request=True)
    assert len(requests) == shared.requests_sent == 1


def test_limit_rejects_tool_follow_up_before_second_http_attempt(monkeypatch):
    requests, usages = [], []

    def fact() -> str:
        """Return a synthetic fact."""
        return "fact"

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json=reply(
                reason="tool_use",
                content=[
                    {"type": "tool_use", "id": "tool_1", "name": "fact", "input": {}},
                ],
            ),
        )

    client_factory(monkeypatch, handler)
    limits = SessionLimits(max_requests=1, max_output_tokens=17)
    with pytest.raises(SessionLimitError) as error:
        run_agent("system", "question", [fact], Settings(), limits=limits, on_usage=usages.append)
    assert isinstance(error.value, AgentError)
    assert len(requests) == limits.requests_sent == limits.responses_observed == 1
    assert requests[0]["max_tokens"] == 17
    assert not usages[0].missing_usage  # The refused request never reached the provider.


def test_same_limit_instance_covers_main_answer_and_repair(monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=reply())

    clients = client_factory(monkeypatch, handler)
    limits = SessionLimits(max_requests=1)
    assert run_agent("system", "main", [], Settings(), limits=limits) == "Answer"
    with pytest.raises(SessionLimitError):
        run_agent("system", "repair", [], Settings(), limits=limits)
    assert len(clients) == len(requests) == 1


def test_every_retry_counts_and_unknown_failed_usage_stays_unknown(monkeypatch):
    requests, usages = [], []
    monkeypatch.setattr("time.sleep", lambda _: None)

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            500,
            json={
                "type": "error",
                "error": {
                    "type": "overloaded_error",
                    "message": "offline retry fixture",
                },
            },
        )

    client_factory(monkeypatch, handler, retries=5)
    limits = SessionLimits(max_requests=2)
    with pytest.raises(SessionLimitError):
        run_agent("system", "question", [], Settings(), limits=limits, on_usage=usages.append)
    assert len(requests) == limits.requests_sent == 2
    assert usages[0].missing_usage
    assert usages[0].estimated_cost_usd is None


def test_thread_recovery_cannot_bypass_pre_send_limit(monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            400,
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "unsupported thread fixture",
                    "details": {
                        "error_code": "thread_unsupported_request",
                        "unsupported": ["tools"],
                    },
                },
            },
        )

    client_factory(monkeypatch, handler)
    agent = ConversationAgent("system", [], Settings(max_requests=1))
    try:
        with pytest.raises(SessionLimitError):
            agent.ask("question")
        assert len(requests) == agent.limits.requests_sent == 1
    finally:
        agent.close()


@pytest.mark.parametrize("stream", [False, True])
def test_optional_compaction_rejected_after_final_answer_preserves_transcript(monkeypatch, stream):
    requests, usages, chunks = [], [], []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        response = reply(text="Complete answer", inputs=150)
        return sse(response) if body.get("stream") else httpx2.Response(200, json=response)

    client_factory(monkeypatch, handler)
    agent = ConversationAgent("system", [], Settings(max_requests=1, compact_threshold=100))
    try:
        answer = agent.ask(
            "First question", on_text=chunks.append if stream else None, on_usage=usages.append
        )
        assert answer.startswith("Complete answer")
        assert "Compaction ignorée" in answer
        # A completed answer stays complete even when the optional next request is refused.
        assert not usages[0].missing_usage
        if stream:
            assert "".join(chunks) == answer
        before = list(agent.thread.messages)
        with pytest.raises(SessionLimitError):
            agent.ask("Question beyond the session limit")
        assert list(agent.thread.messages) == before
        assert "First question" in agent.markdown()
        assert "Complete answer" in agent.markdown()
        assert "Question beyond the session limit" not in agent.markdown()
        assert len(requests) == 1
    finally:
        agent.close()


def test_allowed_compaction_counts_towards_global_chat_limit(monkeypatch):
    requests = []
    replies = [
        reply(1, text="Answer one", inputs=150),
        reply(2, reason="compaction", content=[{"type": "compaction", "content": "Summary"}]),
    ]

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(requests) - 1])

    client_factory(monkeypatch, handler)
    agent = ConversationAgent("system", [], Settings(max_requests=2, compact_threshold=100))
    try:
        assert agent.ask("Question one") == "Answer one"
        assert requests[1]["compaction"] == {"type": "summarize"}
        assert agent.limits.requests_sent == 2
        with pytest.raises(SessionLimitError):
            agent.ask("Question two")
        assert len(requests) == 2
    finally:
        agent.close()


def test_request_limit_is_shared_across_all_chat_questions(monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=reply(len(requests), text=f"Answer {len(requests)}"))

    client_factory(monkeypatch, handler)
    agent = ConversationAgent("system", [], Settings(max_requests=2))
    try:
        assert agent.ask("One") == "Answer 1"
        assert agent.ask("Two") == "Answer 2"
        with pytest.raises(SessionLimitError):
            agent.ask("Three")
        assert len(requests) == 2
        assert "One" in agent.markdown() and "Two" in agent.markdown()
    finally:
        agent.close()


@pytest.mark.parametrize("stream", [False, True])
def test_max_output_tokens_applies_to_actual_http_payload(monkeypatch, stream):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return sse(reply()) if body.get("stream") else httpx2.Response(200, json=reply())

    client_factory(monkeypatch, handler)
    assert (
        run_agent(
            "system",
            "question",
            [],
            Settings(max_output_tokens=37),
            on_text=(lambda text: None) if stream else None,
        )
        == "Answer"
    )
    assert requests[0]["max_tokens"] == 37


def test_default_behavior_keeps_no_session_request_limit_and_16000_output(monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=reply())

    client_factory(monkeypatch, handler)
    assert Settings().max_requests is None
    assert run_agent("system", "question", [], Settings()) == "Answer"
    assert requests[0]["max_tokens"] == 16_000


def test_limit_settings_explicit_options_override_environment(monkeypatch):
    monkeypatch.setenv("LEARN_IT_MAX_REQUESTS", "invalid")
    monkeypatch.setenv("LEARN_IT_MAX_OUTPUT_TOKENS", "invalid")
    settings = Settings.from_env(max_requests=2, max_output_tokens=123)
    assert settings.max_requests == 2
    assert settings.max_output_tokens == 123
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_requests": 0},
        {"max_requests": True},
        {"max_output_tokens": 0},
        {"max_output_tokens": True},
    ],
)
def test_invalid_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
    with pytest.raises(ValueError):
        SessionLimits(**kwargs)


def test_success_after_an_unknown_retry_does_not_claim_a_complete_cost(monkeypatch):
    requests, usages = [], []
    monkeypatch.setattr("time.sleep", lambda _: None)

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx2.Response(
                500,
                json={
                    "type": "error",
                    "error": {
                        "type": "overloaded_error",
                        "message": "unknown prior usage",
                    },
                },
            )
        return httpx2.Response(200, json=reply())

    client_factory(monkeypatch, handler, retries=1)
    limits = SessionLimits(max_requests=2)
    assert (
        run_agent("system", "question", [], Settings(), limits=limits, on_usage=usages.append)
        == "Answer"
    )
    assert len(requests) == limits.requests_sent == 2
    assert limits.responses_observed == 1
    assert usages[0].missing_usage
    assert usages[0].estimated_cost_usd is None


def test_custom_base_url_cannot_skip_generation_limit(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=reply())

    def create():
        return anthropic.Anthropic(
            api_key="synthetic-key-no-network",
            base_url="https://synthetic.invalid/prefix/",
            http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        )

    monkeypatch.setattr(runner, "_client", create)
    limits = SessionLimits(max_requests=1, max_output_tokens=7)
    assert run_agent("system", "question", [], Settings(), limits=limits) == "Answer"
    with pytest.raises(SessionLimitError):
        run_agent("system", "repair", [], Settings(), limits=limits)
    assert len(requests) == 1
    assert requests[0].url.path == "/prefix/v1/messages"
    assert json.loads(requests[0].content)["max_tokens"] == 7


def test_output_only_limit_also_clamps_compaction_request(monkeypatch):
    requests = []
    replies = [
        reply(1, text="Complete answer", inputs=150),
        reply(2, reason="compaction", content=[{"type": "compaction", "content": "Summary"}]),
    ]

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=replies[len(requests) - 1])

    client_factory(monkeypatch, handler)
    agent = ConversationAgent("system", [], Settings(max_output_tokens=37, compact_threshold=100))
    try:
        assert agent.ask("question") == "Complete answer"
        assert [request["max_tokens"] for request in requests] == [37, 37]
        assert agent.limits.requests_sent == 2
    finally:
        agent.close()


def test_extra_body_cannot_override_middleware_output_cap():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=reply())

    limits = SessionLimits(max_output_tokens=7)
    with anthropic.Anthropic(
        api_key="synthetic-key-no-network",
        middleware=[limits.middleware],
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    ) as client:
        client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=100,
            messages=[{"role": "user", "content": "question"}],
            extra_body={"max_tokens": 999},
        )
    assert requests[0]["max_tokens"] == 7


def test_chat_question_interrupted_mid_tool_loop_remains_in_save_transcript(monkeypatch):
    requests = []

    def fact() -> str:
        """Return a synthetic fact."""
        return "fact"

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json=reply(
                reason="tool_use",
                content=[
                    {"type": "tool_use", "id": "tool_1", "name": "fact", "input": {}},
                ],
            ),
        )

    client_factory(monkeypatch, handler)
    agent = ConversationAgent("system", [fact], Settings(max_requests=1))
    try:
        with pytest.raises(SessionLimitError):
            agent.ask("Question interrupted during research")
        saved = agent.markdown()
        assert "Question interrupted during research" in saved
        assert "Réponse interrompue" in saved
        assert "Aucun résultat final" in saved
        with pytest.raises(SessionLimitError):
            agent.ask("Never staged")
        assert "Never staged" not in agent.markdown()
        assert len(requests) == 1
    finally:
        agent.close()
