from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from codearcheo import cli
from codearcheo.agent.runner import BUDGET_BETA, _options
from codearcheo.agent.usage import UsageSummary
from codearcheo.config import Settings


def message(*, model="claude-opus-5-5", tools=0, **usage):
    return SimpleNamespace(
        model=model,
        content=[SimpleNamespace(type="tool_use") for _ in range(tools)],
        usage=SimpleNamespace(**usage),
    )


def test_usage_accumulates_every_request_and_reports_observed_cache_hits():
    summary = UsageSummary()
    summary.add(
        message(tools=1, input_tokens=100, output_tokens=20, cache_creation_input_tokens=2000),
        "claude-opus-5-5",
    )
    assert summary.cache_share == 0
    assert summary.first_cache_read_response is None
    assert summary.second_response_cache_read_tokens is None
    summary.add(
        message(input_tokens=30, output_tokens=10, cache_read_input_tokens=2100), "claude-opus-5-5"
    )
    assert summary.requests == 2
    assert summary.tool_calls == 1
    assert summary.input_tokens == 130
    assert summary.output_tokens == 30
    assert summary.cache_creation_input_tokens == 2000
    assert summary.cache_read_input_tokens == 2100
    assert summary.first_cache_read_response == 2
    assert summary.second_response_cache_read_tokens == 2100
    assert summary.cache_share == pytest.approx(2100 / 4230)
    assert summary.estimated_cost_usd == pytest.approx(0.01154)
    assert "cache écrit 2000, lu 2100" in summary.format()
    assert "cache au 2e retour : 2100 token(s) lus" in summary.format()


def test_cache_diagnostics_distinguish_a_measured_miss_from_missing_usage():
    summary = UsageSummary()
    summary.add(message(input_tokens=100, output_tokens=20), "claude-opus-5-5")
    summary.add(message(input_tokens=200, output_tokens=20), "claude-opus-5-5")
    assert summary.second_response_cache_read_tokens == 0
    assert "cache au 2e retour : 0 token(s) lus" in summary.format()
    missing = UsageSummary()
    missing.add(message(input_tokens=100, output_tokens=20), "claude-opus-5-5")
    missing.add(SimpleNamespace(content=[]), "claude-opus-5-5")
    assert missing.second_response_cache_read_tokens is None
    assert "cache au 2e retour : non mesuré" in missing.format()


def test_one_hour_writes_and_separate_compaction_tokens_are_billed_once():
    summary = UsageSummary()
    summary.add(
        message(
            input_tokens=100,
            output_tokens=10,
            cache_creation_input_tokens=200,
            cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=100),
            iterations=[SimpleNamespace(type="compaction", input_tokens=10, output_tokens=2)],
        ),
        "claude-opus-5-5",
    )
    assert summary.input_tokens == 110
    assert summary.output_tokens == 12
    assert summary.estimated_cost_usd == pytest.approx(
        (110 * 4 + 12 * 20 + 100 * 5 + 100 * 8) / 1e6
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": "unknown"},
        {"speed": "fast"},
        {"service_tier": "priority"},
        {"inference_geo": "us"},
    ],
)
def test_unknown_or_nonstandard_prices_are_not_guessed(overrides):
    summary = UsageSummary()
    summary.add(message(input_tokens=100, output_tokens=20, **overrides), "claude-opus-5-5")
    assert summary.input_tokens == 100
    assert summary.estimated_cost_usd is None
    assert "coût indisponible" in summary.format()


def test_missing_usage_is_not_reported_as_zero_cost():
    summary = UsageSummary()
    summary.add(SimpleNamespace(content=[]), "claude-opus-5-5")
    assert summary.missing_usage
    assert summary.estimated_cost_usd is None


def test_api_task_budget_has_validated_units_and_keeps_effort_and_fallback():
    options = _options(Settings(budget=30_000))
    assert options["output_config"] == {
        "effort": "medium",
        "task_budget": {"type": "tokens", "total": 30_000},
    }
    assert BUDGET_BETA in options["betas"]
    assert options["fallbacks"] == "default"
    with pytest.raises(ValueError, match="20 000"):
        Settings(budget=19_999)


def test_command_options_override_environment(project, monkeypatch):
    monkeypatch.setenv("CODEARCHEO_MODEL", "env-model")
    monkeypatch.setenv("CODEARCHEO_EFFORT", "low")
    monkeypatch.setenv("CODEARCHEO_BUDGET", "25000")
    session = cli._session(str(project.root), model="cli-model", effort="", budget=40_000)
    assert session.settings.model == "cli-model"
    assert session.settings.effort == ""
    assert session.settings.budget == 40_000
    inherited = cli._session(str(project.root))
    assert inherited.settings.model == "env-model"
    assert inherited.settings.effort == "low"
    assert inherited.settings.budget == 25_000


def test_explicit_flags_can_override_invalid_environment_values():
    from unittest.mock import patch

    with patch.dict("os.environ", {"CODEARCHEO_BUDGET": "invalid", "CODEARCHEO_EFFORT": "invalid"}):
        settings = Settings.from_env(effort="medium", budget=30_000)
    assert settings.effort == "medium"
    assert settings.budget == 30_000


@pytest.mark.parametrize("stream", [True, False])
def test_ask_cli_prints_the_answer_once(project, monkeypatch, stream):
    def fake_ask(session, question):
        assert question == "Question"
        assert session.settings.model == "my-model"
        assert session.settings.effort == "medium"
        assert session.settings.budget == 30_000
        if session.on_text:
            session.on_text("CANARY_ANSWER")
        return "CANARY_ANSWER"

    monkeypatch.setattr(cli.features, "ask", fake_ask)
    result = CliRunner().invoke(
        cli.app,
        [
            "ask",
            "Question",
            "-p",
            str(project.root),
            "--model",
            "my-model",
            "--effort",
            "medium",
            "--budget",
            "30000",
            "--stream" if stream else "--no-stream",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.count("CANARY_ANSWER") == 1
