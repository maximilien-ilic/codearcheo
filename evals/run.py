"""Run learn-it on the reference cases with the real Claude API, then score the results.

    uv run python -m evals.run           # every reference project
    uv run python -m evals.run shop      # only the named ones

Every run spends API tokens, so neither pytest nor the CI runs it. Results are printed,
and saved as JSON in `<LEARN_IT_CACHE_DIR>/evals/`.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
import tomllib
from contextlib import nullcontext
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.fixtures import build_fixture
from evals.scoring import Check, score_answer, score_decisions
from learn_it import features, git
from learn_it.agent.runner import AgentError
from learn_it.analyzers import scan
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.sources import Project, parse_github
from learn_it.store import Store

CASES = Path(__file__).with_name("cases.toml")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def load_cases() -> list[dict[str, Any]]:
    specs = tomllib.loads(CASES.read_text(encoding="utf-8"))["projects"]
    validate_cases(specs)
    return specs


def validate_cases(specs: list[dict[str, Any]]) -> None:
    """Validate every reference offline; real repository checks happen after checkout."""
    projects, cases = set(), set()
    for spec in specs:
        name = spec["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) or name in projects:
            raise ValueError(f"Invalid or duplicate project name: {name}")
        projects.add(name)
        if not spec.get("language"):
            raise ValueError(f"{name}: language is required")
        if spec["source"] not in {"synthetic", "synthetic-github"}:
            if not parse_github(spec["source"]) or not _SHA.fullmatch(spec.get("ref", "")):
                raise ValueError(f"{name}: a GitHub source requires an immutable full SHA")
        elif spec.get("fixture", "shop") not in {"shop", "shop-injection", "github-rationale"}:
            raise ValueError(f"{name}: unknown fixture")
        for case in spec["cases"]:
            case_id, command = case["id"], case["command"]
            if case_id in cases or command not in {"ask", "decisions", "why", "review"}:
                raise ValueError(f"Invalid or duplicate case: {case_id}")
            cases.add(case_id)
            if command == "ask" and not case.get("question"):
                raise ValueError(f"{case_id}: ask requires a question")
            if command == "why" and not case.get("target"):
                raise ValueError(f"{case_id}: why requires a target")
            for path in case.get("cite_any_file", []):
                if Path(path).is_absolute() or ".." in Path(path).parts:
                    raise ValueError(f"{case_id}: evidence must stay inside the reference project")


def prepare(spec: dict[str, Any], workdir: Path) -> Project:
    """The reference project on disk: rebuilt when synthetic, else cloned at its pinned commit."""
    root = workdir / spec["name"]
    if spec["source"] == "synthetic-github":
        from evals.github_project import build_github_project

        shutil.rmtree(root, ignore_errors=True)
        return Project(root=build_github_project(root), name=spec["name"])
    if spec["source"] == "synthetic":
        shutil.rmtree(root, ignore_errors=True)
        fixture = spec.get("fixture", "shop")
        return Project(root=build_fixture(root, fixture), name=spec["name"])

    if not parse_github(spec["source"]) or not _SHA.match(spec["ref"]):
        raise ValueError(f"{spec['name']} : source GitHub ou ref (sha complet) invalide")
    if not (root / ".git").exists():
        workdir.mkdir(parents=True, exist_ok=True)
        git.run(workdir, "clone", "--quiet", spec["source"], spec["name"])
    try:
        git.run(root, "checkout", "--quiet", "--detach", spec["ref"])
    except git.GitError:  # pinned after the clone was made
        git.run(root, "fetch", "--quiet", "origin")
        git.run(root, "checkout", "--quiet", "--detach", spec["ref"])
    return Project(root=root, name=spec["name"], origin=spec["source"])


def run_case(session: Session, case: dict[str, Any], canary: str | None) -> list[Check]:
    root = session.project.root
    try:
        if case["command"] == "decisions":
            answer = features.decisions(session)
            return score_decisions(session.store.load_decisions(), case, root, canary,
                                   answer=answer)
        if case["command"] == "ask":
            answer = features.ask(session, case["question"])
        elif case["command"] == "why":
            answer = features.why(session, case["target"])
        elif case["command"] == "review":
            answer = features.review(session)
        else:
            raise ValueError(f"Unknown evaluation command: {case['command']}")
        return score_answer(answer, case, root, canary)
    except AgentError as exc:
        return [Check("réponse obtenue", False, str(exc))]


def main(names: list[str]) -> int:
    settings = Settings.from_env()
    workdir = settings.cache_dir / "evals"
    results = []
    measurements = []
    for spec in load_cases():
        if names and spec["name"] not in names:
            continue
        started = time.perf_counter()
        project = prepare(spec, workdir)
        prepared = time.perf_counter()
        profile = scan(project)
        scanned = time.perf_counter()
        minimum = spec.get("minimum_commits", 0)
        if profile.commits < minimum:
            raise ValueError(f"{spec['name']}: expected at least {minimum} commits, "
                             f"got {profile.commits} (full history is required)")
        measurements.append({
            "project": spec["name"], "sha": profile.head, "commits": profile.commits,
            "files": profile.files, "preparation_seconds": prepared - started,
            "scan_seconds": scanned - prepared,
        })
        session = Session(project, profile, Store(project.root), settings)
        for case in spec["cases"]:
            started = time.perf_counter()
            context = nullcontext()
            if spec["source"] == "synthetic-github":
                from evals.github_project import replay_github

                context = replay_github()
            with context:
                checks = run_case(session, case, spec.get("canary"))
            passed = all(check.ok for check in checks)
            results.append(
                {"case": case["id"], "project": spec["name"], "passed": passed,
                 "elapsed_seconds": time.perf_counter() - started,
                 "checks": [asdict(c) for c in checks]}
            )
            print(f"{'✓' if passed else '✗'} {case['id']}")
            for check in checks:
                if not check.ok:
                    print(f"    ✗ {check.name}" + (f" : {check.detail}" if check.detail else ""))

    passed = sum(result["passed"] for result in results)
    print(f"\n{passed}/{len(results)} cas réussis · {settings.model}, effort {settings.effort}")
    workdir.mkdir(parents=True, exist_ok=True)
    output = workdir / f"results-{datetime.now():%Y%m%d-%H%M%S}.json"
    report = {"model": settings.model, "effort": settings.effort,
              "projects": measurements, "results": results}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Résultats : {output}")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
