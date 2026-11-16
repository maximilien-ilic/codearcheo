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
import tomllib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.scoring import Check, score_answer, score_decisions
from evals.shop import build_shop
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
    return tomllib.loads(CASES.read_text(encoding="utf-8"))["projects"]


def prepare(spec: dict[str, Any], workdir: Path) -> Project:
    """The reference project on disk: rebuilt when synthetic, else cloned at its pinned commit."""
    root = workdir / spec["name"]
    if spec["source"] == "synthetic":
        shutil.rmtree(root, ignore_errors=True)
        return Project(root=build_shop(root), name=spec["name"])

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
            return score_decisions(
                session.store.load_decisions(), case, root, canary, answer=answer
            )
        return score_answer(features.ask(session, case["question"]), case, root, canary)
    except AgentError as exc:
        return [Check("réponse obtenue", False, str(exc))]


def main(names: list[str]) -> int:
    settings = Settings.from_env()
    workdir = settings.cache_dir / "evals"
    results = []
    for spec in load_cases():
        if names and spec["name"] not in names:
            continue
        project = prepare(spec, workdir)
        session = Session(project, scan(project), Store(project.root), settings)
        for case in spec["cases"]:
            checks = run_case(session, case, spec.get("canary"))
            passed = all(check.ok for check in checks)
            results.append(
                {"case": case["id"], "passed": passed, "checks": [asdict(c) for c in checks]}
            )
            print(f"{'✓' if passed else '✗'} {case['id']}")
            for check in checks:
                if not check.ok:
                    print(f"    ✗ {check.name}" + (f" : {check.detail}" if check.detail else ""))

    passed = sum(result["passed"] for result in results)
    print(f"\n{passed}/{len(results)} cas réussis · {settings.model}, effort {settings.effort}")
    workdir.mkdir(parents=True, exist_ok=True)
    output = workdir / f"results-{datetime.now():%Y%m%d-%H%M%S}.json"
    report = {"model": settings.model, "effort": settings.effort, "results": results}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Résultats : {output}")
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
