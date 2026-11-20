"""Record only numeric review usage and estimate workload from read-only GitHub data."""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import statistics
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

REPO = "maximilien-ilic/codearcheo"
WORKFLOW = "claude-review.yml"
MAX_EXECUTION_BYTES = 64 * 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
STANDARD_LINUX = {"ubuntu-latest", "ubuntu-26.04", "ubuntu-24.04", "ubuntu-22.04"}


def number(value: Any, *, integer: bool = False) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(value)
    except OverflowError:
        return None
    if value < 0 or not finite or (integer and int(value) != value):
        return None
    return int(value) if integer else float(value)


def extract_metrics(messages: Any) -> dict[str, Any]:
    """The pinned action writes an array of SDK messages; never retain their text."""
    results = [item for item in messages if isinstance(item, dict) and item.get("type") == "result"]
    if not results:
        return {"metrics_available": False, "reason": "missing_result", "api_equivalent_usd": None}
    result = results[-1]
    models = result.get("modelUsage")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    tokens = {}
    for field, model_field in (
        ("input_tokens", "inputTokens"),
        ("output_tokens", "outputTokens"),
        ("cache_read_input_tokens", "cacheReadInputTokens"),
        ("cache_creation_input_tokens", "cacheCreationInputTokens"),
    ):
        if isinstance(models, dict) and models:
            values = [
                number(model.get(model_field), integer=True) if isinstance(model, dict) else None
                for model in models.values()
            ]
            tokens[field] = sum(values) if all(value is not None for value in values) else None
        else:
            tokens[field] = number(usage.get(field), integer=True)
    duration = number(result.get("duration_ms"))
    return {
        "metrics_available": True,
        "reason": None,
        "api_equivalent_usd": number(result.get("total_cost_usd")),
        "duration_seconds": duration / 1000 if duration is not None else None,
        "turns": number(result.get("num_turns"), integer=True),
        "tokens": tokens,
    }


def execution_metrics(path: Path | None) -> dict[str, Any]:
    try:
        if path is None or not path.is_file():
            reason = "missing_execution_file"
        elif path.stat().st_size > MAX_EXECUTION_BYTES:
            reason = "oversized_execution_file"
        else:
            messages = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(messages, list):
                return extract_metrics(messages)
            reason = "invalid_execution_file"
    except (OSError, ValueError, RecursionError):
        reason = "unreadable_execution_file"
    return {"metrics_available": False, "reason": reason, "api_equivalent_usd": None}


def github(endpoint: str, *, paginate: bool = False, binary: bool = False) -> Any:
    command = ["gh", "api", "--method", "GET", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    output = subprocess.check_output(command, stderr=subprocess.PIPE, timeout=60)
    return output if binary else json.loads(output)


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def archived_usage(repo: str, run: dict, request=github) -> dict[str, Any] | None:
    name = f"claude-review-usage-{run['id']}-{run['run_attempt']}"
    try:
        payload = request(
            f"repos/{repo}/actions/runs/{run['id']}/artifacts?" + urlencode({"name": name})
        )
    except (subprocess.SubprocessError, ValueError):
        return None
    artifacts = [
        item for item in payload["artifacts"] if item["name"] == name and not item["expired"]
    ]
    if len(artifacts) != 1 or artifacts[0]["size_in_bytes"] > MAX_ARTIFACT_BYTES:
        return None
    try:
        data = request(f"repos/{repo}/actions/artifacts/{artifacts[0]['id']}/zip", binary=True)
    except subprocess.SubprocessError:
        # An expired or otherwise unavailable download only affects this sample.
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("usage.json")
            if info.file_size > MAX_ARTIFACT_BYTES:
                return None
            usage = json.loads(archive.read(info))
        if (
            not isinstance(usage, dict)
            or usage.get("schema_version") != 1
            or usage.get("metrics_available") is not True
        ):
            return None
        if (
            usage.get("repository"),
            usage.get("run_id"),
            usage.get("run_attempt"),
        ) != (
            repo,
            run["id"],
            run["run_attempt"],
        ):
            return None
        sha = usage.get("sha")
        # A workflow_run executes on the default branch tip but reviews the CI's SHA.
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            return None
        if run["event"] != "workflow_run" and sha != run["head_sha"]:
            return None
        return {"api_equivalent_usd": number(usage.get("api_equivalent_usd"))}
    except (OSError, ValueError, KeyError, RecursionError, zipfile.BadZipFile):
        return None


def report(
    repo: str,
    *,
    days: int,
    now: datetime,
    scenario: float | None = None,
    request=github,
) -> dict[str, Any]:
    repository = request(f"repos/{repo}")
    workflow = request(f"repos/{repo}/actions/workflows/{WORKFLOW}")
    start = max(now - timedelta(days=days), timestamp(workflow["created_at"]))
    if start >= now:
        raise ValueError("La fenêtre d'observation du workflow est vide.")
    all_runs = {}
    for event in ("push", "workflow_run"):
        query = urlencode(
            {
                "branch": "master",
                "event": event,
                "per_page": 100,
                "created": f"{start.isoformat()}..{now.isoformat()}",
            }
        )
        pages = request(f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?{query}", paginate=True)
        event_runs = {run["id"]: run for page in pages for run in page["workflow_runs"]}
        if len(event_runs) < pages[0]["total_count"]:
            raise ValueError("Historique tronqué : réduire --days.")
        all_runs.update(event_runs)
    runs = [run for run in all_runs.values() if start <= timestamp(run["created_at"]) <= now]
    samples = []
    standard_runners = True
    for initial in runs:
        for attempt in range(1, initial["run_attempt"] + 1):
            run = {**initial, "run_attempt": attempt}
            sample = {
                "run_id": run["id"], "run_attempt": run["run_attempt"],
                "created_at": run["created_at"], "model_started": None,
                "missing_token": False, "api_equivalent_usd": None,
            }
            # Every direct push run in codearcheo used an action that rejects push
            # before calling Claude. Keep these runs in the trigger history.
            legacy_push = repo.casefold() == REPO and run["event"] == "push"
            if legacy_push:
                sample.update(model_started=False, api_equivalent_usd=0.0)
            samples.append(sample)
            try:
                jobs = request(
                    f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs"
                )
            except (subprocess.SubprocessError, ValueError):
                standard_runners = False
                continue
            steps = [step for job in jobs["jobs"] for step in job.get("steps", [])]
            standard_runners &= bool(jobs["jobs"]) and all(
                set(job.get("labels", [])) & STANDARD_LINUX for job in jobs["jobs"]
            )
            model_steps = [
                step
                for step in steps
                if step["name"] == "Revue Claude"
                or step["name"].startswith("Run anthropics/claude-code-action@")
            ]
            started = None
            if any(
                step.get("started_at") and step.get("conclusion") != "skipped"
                for step in model_steps
            ):
                started = True
            elif model_steps and all(step.get("conclusion") == "skipped" for step in model_steps):
                started = False
            no_token = any(
                step["name"] == "Secret absent" and step.get("conclusion") == "success"
                for step in steps
            )
            cost = None
            if legacy_push or no_token or started is False:
                started, cost = False, 0.0
            elif started:
                usage = archived_usage(repo, run, request)
                cost = usage["api_equivalent_usd"] if usage else None
            sample.update(model_started=started, missing_token=no_token, api_equivalent_usd=cost)
    observed_days = (now - start).total_seconds() / 86400
    projected = len(runs) * 30 / observed_days
    active = [sample for sample in samples if sample["model_started"] is True]
    costs = [sample["api_equivalent_usd"] for sample in active]
    complete = all(sample["api_equivalent_usd"] is not None for sample in samples)
    measured = statistics.mean(costs) if costs and complete else None
    per_review = scenario if scenario is not None else measured
    active_triggers = {sample["run_id"] for sample in active}
    attempts = (
        1.0 if scenario is not None else len(active) / len(active_triggers) if active else None
    )
    per_trigger = per_review * attempts if per_review is not None and attempts is not None else None
    return {
        "schema_version": 1,
        "repository": repo,
        "generated_at": now.isoformat(),
        "window_start": start.isoformat(),
        "observed_days": observed_days,
        "short_history": observed_days < 7,
        "push_triggers": len(runs),
        "model_reviews_started": len(active),
        "usage_missing": sum(sample["api_equivalent_usd"] is None for sample in samples),
        "known_api_equivalent_subtotal_usd": sum(
            sample["api_equivalent_usd"]
            for sample in samples
            if sample["api_equivalent_usd"] is not None
        ),
        "projected_30d_triggers_at_same_rate": projected,
        "per_review_api_equivalent_usd": per_review,
        "attempts_per_started_trigger": attempts,
        "per_trigger_api_equivalent_usd": per_trigger,
        "projection_basis": (
            "user_scenario"
            if scenario is not None
            else "measured_reviews"
            if measured is not None
            else "unavailable"
        ),
        "projection_assumption": "same push rate; every trigger starts a review when enabled",
        "projected_30d_api_equivalent_usd": projected * per_trigger
        if per_trigger is not None
        else None,
        "standard_public_runner_compute_usd": (
            0.0 if repository["visibility"] == "public" and standard_runners else None
        ),
        "claude_invoice_usd": None,
        "runs": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Export numeric metrics from the action's JSON.")
    record.add_argument("--execution-file", type=Path)
    record.add_argument("--run-id", type=int, required=True)
    record.add_argument("--attempt", type=int, required=True)
    record.add_argument("--sha", required=True)
    record.add_argument(
        "--conclusion", choices=("success", "failure", "unknown"), default="unknown"
    )
    record.add_argument("--repo", default=REPO)
    record.add_argument("--output", type=Path, required=True)
    collect = commands.add_parser("report", help="Read GitHub history; never starts a review.")
    collect.add_argument("--repo", default=REPO)
    collect.add_argument("--days", type=int, default=7)
    collect.add_argument("--per-review-usd", type=float, help="Explicit API-equivalent scenario.")
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
            raise ValueError("Dépôt attendu : propriétaire/nom.")
        if args.command == "record":
            if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
                raise ValueError("Un SHA complet est requis.")
            result = {
                "schema_version": 1,
                "repository": args.repo,
                "run_id": args.run_id,
                "run_attempt": args.attempt,
                "sha": args.sha,
                "conclusion": args.conclusion,
                "recorded_at": datetime.now(UTC).isoformat(),
                **execution_metrics(args.execution_file),
            }
        else:
            if args.days < 1 or (
                args.per_review_usd is not None and number(args.per_review_usd) is None
            ):
                raise ValueError("Fenêtre positive et scénario monétaire fini non négatif requis.")
            result = report(
                args.repo, days=args.days, now=datetime.now(UTC), scenario=args.per_review_usd
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("Relevé indisponible : vérifier les entrées et l'accès GitHub en lecture.")
        return 1
    print(f"Relevé enregistré : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
