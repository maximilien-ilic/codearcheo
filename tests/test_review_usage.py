"""Review cost reports preserve missing data and never export conversation content."""

import io
import json
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from scripts import review_usage as usage

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
SHA = "1" * 40


def result(cost=0.25):
    return {
        "type": "result", "total_cost_usd": cost, "duration_ms": 2000, "num_turns": 3,
        "modelUsage": {"claude-model": {
            "inputTokens": 10, "outputTokens": 20, "cacheReadInputTokens": 30,
            "cacheCreationInputTokens": 40,
        }},
    }


def archive(payload):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("usage.json", json.dumps(payload))
    return data.getvalue()


class GitHub:
    def __init__(self, *, costs=(None,), skipped=True, repo=usage.REPO):
        self.costs = costs
        self.skipped = skipped
        self.visibility = "public"
        self.total_count = len(costs)
        self.sha = SHA
        self.event = "workflow_run"
        self.repo = repo

    def __call__(self, endpoint, **options):
        if endpoint == f"repos/{self.repo}":
            return {"visibility": self.visibility}
        if endpoint.endswith(f"/workflows/{usage.WORKFLOW}"):
            return {"created_at": (NOW - timedelta(days=2)).isoformat()}
        if "/workflows/" in endpoint and "/runs?" in endpoint:
            if parse_qs(urlsplit(endpoint).query)["event"] != [self.event]:
                return [{"total_count": 0, "workflow_runs": []}]
            return [{"total_count": self.total_count, "workflow_runs": [
                {"id": i, "run_attempt": 1, "head_sha": SHA, "event": self.event,
                 "created_at": (NOW - timedelta(hours=i)).isoformat()}
                for i in range(1, len(self.costs) + 1)
            ]}]
        if endpoint.endswith("/jobs"):
            return {"jobs": [{"labels": ["ubuntu-latest"], "steps": [
                {"name": "Secret absent", "conclusion": "success" if self.skipped else "skipped"},
                {"name": "Revue Claude", "conclusion": "skipped" if self.skipped else "success",
                 "started_at": NOW.isoformat()},
            ]}]}
        if "/artifacts?" in endpoint:
            run_id = int(endpoint.split("/runs/")[1].split("/")[0])
            cost = self.costs[run_id - 1]
            return {"artifacts": [] if cost is None else [{
                "id": run_id, "name": f"claude-review-usage-{run_id}-1",
                "expired": False, "size_in_bytes": 1000,
            }]}
        if endpoint.endswith("/zip"):
            artifact_id = int(endpoint.split("/artifacts/")[1].split("/")[0])
            return archive({
                "schema_version": 1, "repository": self.repo, "run_id": artifact_id,
                "run_attempt": 1, "sha": self.sha, "metrics_available": True,
                "api_equivalent_usd": self.costs[artifact_id - 1],
            })
        pytest.fail(f"Unexpected GitHub request: {endpoint}")


def test_numeric_metrics_never_copy_prompts_answers_or_model_names():
    marker = "PRIVATE_CONVERSATION_CANARY"
    terminal = result()
    terminal.update(result=marker, structured_output={"private": marker})
    terminal["modelUsage"][marker] = terminal["modelUsage"].pop("claude-model")
    measured = usage.extract_metrics([
        {"type": "assistant", "content": marker}, {"type": "tool_result", "content": marker},
        terminal,
    ])
    assert marker not in json.dumps(measured)
    assert measured["api_equivalent_usd"] == 0.25
    assert measured["tokens"]["cache_read_input_tokens"] == 30
    assert measured["duration_seconds"] == 2


@pytest.mark.parametrize("bad", [None, True, "1.2", -1, float("nan"), float("inf"), 10**1000])
def test_invalid_cost_data_is_unknown_instead_of_zero(bad):
    assert usage.extract_metrics([result(bad)])["api_equivalent_usd"] is None


def test_missing_execution_file_does_not_invent_a_free_review(tmp_path):
    record = usage.execution_metrics(tmp_path / "missing.json")
    assert record["api_equivalent_usd"] is None
    assert record["metrics_available"] is False


def test_skipped_workflows_do_not_predict_free_model_reviews():
    measured = usage.report(usage.REPO, days=7, now=NOW, request=GitHub(costs=(None, None)))
    assert measured["push_triggers"] == 2
    assert measured["model_reviews_started"] == 0
    assert measured["known_api_equivalent_subtotal_usd"] == 0
    assert measured["per_review_api_equivalent_usd"] is None
    assert measured["projected_30d_api_equivalent_usd"] is None
    assert measured["projection_basis"] == "unavailable"
    assert measured["projected_30d_triggers_at_same_rate"] == 30
    assert measured["short_history"]
    assert measured["standard_public_runner_compute_usd"] == 0


def test_complete_measured_reviews_can_project_api_equivalent_usage():
    measured = usage.report(usage.REPO, days=7, now=NOW,
                            request=GitHub(costs=(0.25, 0.75), skipped=False))
    assert measured["per_review_api_equivalent_usd"] == 0.5
    assert measured["projected_30d_api_equivalent_usd"] == 15
    assert measured["projection_basis"] == "measured_reviews"
    assert measured["claude_invoice_usd"] is None


def test_a_missing_review_artifact_cannot_bias_the_cost_average_downward():
    measured = usage.report(usage.REPO, days=7, now=NOW,
                            request=GitHub(costs=(0.25, None), skipped=False))
    assert measured["known_api_equivalent_subtotal_usd"] == 0.25
    assert measured["usage_missing"] == 1
    assert measured["per_review_api_equivalent_usd"] is None


@pytest.mark.parametrize("phase", ["listing", "download"])
def test_unavailable_artifact_data_preserves_the_report(phase):
    base = GitHub(costs=(0.25, 0.75), skipped=False)

    def request(endpoint, **options):
        if ((phase == "download" and endpoint.endswith("/artifacts/2/zip"))
                or (phase == "listing" and "/runs/2/artifacts?" in endpoint)):
            raise subprocess.CalledProcessError(1, ["gh", "api"], stderr=b"HTTP 410")
        return base(endpoint, **options)

    measured = usage.report(usage.REPO, days=7, now=NOW, request=request)
    assert measured["model_reviews_started"] == 2
    assert measured["known_api_equivalent_subtotal_usd"] == 0.25
    assert measured["usage_missing"] == 1
    assert measured["projected_30d_api_equivalent_usd"] is None


def test_an_unavailable_job_keeps_the_other_attempts():
    base = GitHub(costs=(0.25, 0.75), skipped=False)

    def request(endpoint, **options):
        if "/runs/2/attempts/1/jobs" in endpoint:
            raise subprocess.CalledProcessError(1, ["gh", "api"], stderr=b"HTTP 502")
        return base(endpoint, **options)

    measured = usage.report(usage.REPO, days=7, now=NOW, request=request)
    assert measured["known_api_equivalent_subtotal_usd"] == 0.25
    assert measured["usage_missing"] == 1
    assert measured["projected_30d_api_equivalent_usd"] is None
    assert measured["standard_public_runner_compute_usd"] is None


@pytest.mark.parametrize("endpoint_part", ["/runs/2/artifacts?", "/runs/2/attempts/1/jobs"])
def test_unreadable_github_response_preserves_other_attempts(endpoint_part):
    base = GitHub(costs=(0.25, 0.75), skipped=False)

    def request(endpoint, **options):
        if endpoint_part in endpoint:
            return json.loads(b"<invalid response>")
        return base(endpoint, **options)

    measured = usage.report(usage.REPO, days=7, now=NOW, request=request)
    assert measured["known_api_equivalent_subtotal_usd"] == 0.25
    assert measured["usage_missing"] == 1
    assert measured["runs"][1]["api_equivalent_usd"] is None
    assert measured["projected_30d_api_equivalent_usd"] is None


def test_a_pending_model_step_is_not_counted_as_a_free_attempt():
    base = GitHub(costs=(0.25,), skipped=False)

    def request(endpoint, **options):
        response = base(endpoint, **options)
        if endpoint.endswith("/jobs"):
            response["jobs"][0]["steps"][1].update(started_at=None, conclusion=None)
        return response

    measured = usage.report(usage.REPO, days=7, now=NOW, request=request)
    assert measured["runs"][0]["model_started"] is None
    assert measured["runs"][0]["api_equivalent_usd"] is None
    assert measured["usage_missing"] == 1


@pytest.mark.parametrize("second_started", [True, False])
def test_a_rerun_does_not_erase_the_cost_of_the_first_attempt(second_started):
    base = GitHub(costs=(0.25,), skipped=False)

    def request(endpoint, **options):
        if "/workflows/" in endpoint and "/runs?" in endpoint:
            pages = base(endpoint, **options)
            for run in pages[0]["workflow_runs"]:
                run["run_attempt"] = 2
            return pages
        if endpoint.endswith("/jobs"):
            jobs = base(endpoint, **options)
            if "/attempts/2/" in endpoint and not second_started:
                jobs["jobs"][0]["steps"][1]["conclusion"] = "skipped"
            return jobs
        if "/artifacts?" in endpoint:
            attempt = 2 if endpoint.endswith("-2") else 1
            return {"artifacts": [{"id": attempt, "expired": False, "size_in_bytes": 1000,
                                   "name": f"claude-review-usage-1-{attempt}"}]}
        if endpoint.endswith("/zip"):
            attempt = int(endpoint.split("/artifacts/")[1].split("/")[0])
            return archive({
                "schema_version": 1, "repository": usage.REPO, "run_id": 1,
                "run_attempt": attempt, "sha": SHA, "metrics_available": True,
                "api_equivalent_usd": 0.25 if attempt == 1 else 0.75,
            })
        return base(endpoint, **options)

    measured = usage.report(usage.REPO, days=7, now=NOW, request=request)
    assert measured["push_triggers"] == 1
    assert len(measured["runs"]) == 2
    assert measured["known_api_equivalent_subtotal_usd"] == (1 if second_started else 0.25)
    assert measured["projected_30d_api_equivalent_usd"] == (15 if second_started else 3.75)


def test_scenarios_are_explicitly_separate_from_measured_costs():
    measured = usage.report(usage.REPO, days=7, now=NOW, scenario=1, request=GitHub())
    assert measured["projection_basis"] == "user_scenario"
    assert measured["projected_30d_api_equivalent_usd"] == 15
    assert measured["known_api_equivalent_subtotal_usd"] == 0


def test_artifacts_from_a_different_commit_are_not_used():
    github = GitHub(costs=(0.25,), skipped=False, repo="example/other")
    github.event = "push"
    github.sha = "2" * 40
    measured = usage.report(github.repo, days=7, now=NOW, request=github)
    assert measured["usage_missing"] == 1
    assert measured["projected_30d_api_equivalent_usd"] is None


@pytest.mark.parametrize("sha, expected", [("2" * 40, 0.75), ("invalid", None)])
def test_report_keeps_push_history_and_accepts_the_upstream_ci_sha(sha, expected):
    legacy = GitHub(costs=(None,), skipped=False)
    legacy.event = "push"
    current = GitHub(costs=(0.25, 0.75), skipped=False)
    current.sha = sha

    def request(endpoint, **options):
        if "/workflows/" in endpoint and "/runs?" in endpoint:
            pages = current(endpoint, **options)
            if pages[0]["workflow_runs"]:
                return [{"total_count": 1, "workflow_runs": pages[0]["workflow_runs"][1:]}]
        if "/runs/2/" in endpoint or "/artifacts/2/" in endpoint:
            return current(endpoint, **options)
        response = legacy(endpoint, **options)
        if endpoint.endswith("/jobs"):
            response["jobs"][0]["steps"][1]["conclusion"] = "failure"
        return response

    measured = usage.report(usage.REPO, days=7, now=NOW, request=request)
    assert measured["push_triggers"] == 2
    assert {run["run_id"]: run["api_equivalent_usd"] for run in measured["runs"]} == {
        1: 0.0, 2: expected,
    }
    assert measured["model_reviews_started"] == 1
    assert measured["usage_missing"] == int(expected is None)
    assert measured["projection_basis"] == ("measured_reviews" if expected else "unavailable")


def test_a_truncated_history_cannot_produce_a_monthly_projection():
    github = GitHub()
    github.total_count = 1000
    with pytest.raises(ValueError, match="tronqué"):
        usage.report(usage.REPO, days=7, now=NOW, request=github)


def test_runner_pricing_is_not_guessed_for_private_repositories():
    github = GitHub()
    github.visibility = "private"
    assert usage.report(usage.REPO, days=7, now=NOW, request=github)[
        "standard_public_runner_compute_usd"
    ] is None


def test_workflow_uploads_only_sanitized_metrics():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / ".github/workflows/claude-review.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["review"]["steps"]
    uploaded = next(step for step in steps if "upload-artifact" in step.get("uses", ""))
    assert uploaded["with"]["path"] == "${{ runner.temp }}/review-usage/usage.json"
    assert uploaded["with"]["retention-days"] == 7
    recorder = next(step for step in steps if step.get("id") == "usage")
    assert 'python3 "$RUNNER_TEMP/review_usage.py" record' in recorder["run"]
    claude = next(step for step in steps if step.get("id") == "claude")
    assert claude["with"]["bot_name"] == "${{ github.repository_owner }}"
    assert claude["with"]["bot_id"] == "${{ github.repository_owner_id }}"
    assert json.loads(claude["with"]["settings"])["attribution"] == {
        "commit": "", "pr": "", "sessionUrl": False,
    }
