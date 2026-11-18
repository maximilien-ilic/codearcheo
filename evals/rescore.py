"""Regrade saved generations locally, without preparing projects or calling a model.

    uv run python -m evals.rescore ~/.cache/learn-it/evals/results-....json

The reference checkouts must still be present at their recorded commits. The saved case
definitions and outputs are reused; this measures the grader, never a new model response.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.artifacts import fingerprint, save_report
from evals.scoring import score_answer, score_decisions
from learn_it import git
from learn_it.domain import Decision


def rescore(report: dict[str, Any], projects_dir: Path) -> dict[str, Any]:
    if report.get("schema_version") != 2:
        raise ValueError("Ce rapport ne contient pas les réponses archivées (format 2 requis).")
    heads = {project["project"]: project["sha"] for project in report["projects"]}
    fingerprints = {
        project["project"]: project["worktree_fingerprint"] for project in report["projects"]
    }
    verified = set()
    results = []
    for result in report["results"]:
        if result["status"] == "error":
            results.append(dict(result))
            continue  # no model answer to grade; retain the execution error
        name = result["project"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError(f"Nom de projet invalide : {name}")
        root = projects_dir / name
        if not heads.get(name) or git.head(root) != heads[name]:
            raise ValueError(f"{name} : checkout absent ou SHA différent de celui du rapport.")
        if name not in verified:
            if fingerprint(root) != fingerprints[name]:
                raise ValueError(f"{name} : les fichiers diffèrent de ceux de la mesure.")
            verified.add(name)
        answer = result.get("answer")
        if not isinstance(answer, str):
            raise ValueError(f"{result['case']} : réponse archivée absente.")
        case, canary = result["case_definition"], result.get("canary")
        if case["command"] == "decisions":
            records = [Decision.model_validate(record) for record in result["decisions"]]
            checks = score_decisions(records, case, root, canary, answer=answer)
        elif case["command"] in {"ask", "why", "review"}:
            checks = score_answer(answer, case, root, canary)
        else:
            raise ValueError(f"Commande inconnue : {case['command']}")
        # Regrading the content cannot validate missing runtime instrumentation.
        guards = [check for check in result["checks"]
                  if check["name"] == "correction/comparaison disponible"]
        serialized = [asdict(check) for check in checks] + guards
        passed = all(check["ok"] for check in serialized)
        results.append({
            **result, "previous_passed": result["passed"], "previous_checks": result["checks"],
            "passed": passed, "status": "passed" if passed else "failed", "checks": serialized,
        })
    code_root = Path(__file__).resolve().parents[1]
    revision = git.head(code_root)
    return {
        **report, "results": results, "rescored_at": datetime.now(UTC).isoformat(),
        "scoring_revision": revision,
        "scoring_dirty": bool(git.run(code_root, "status", "--porcelain")) if revision else None,
    }


def main(path: Path, *, projects_dir: Path | None = None) -> int:
    try:
        original = json.loads(path.read_text(encoding="utf-8"))
        report = rescore(original, projects_dir if projects_dir is not None else path.parent)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Recalcul impossible : {exc}", file=sys.stderr)
        return 2
    output = path.with_name(f"rescore-{path.stem}-{uuid.uuid4().hex[:8]}.json")
    report["source_report"] = str(path.resolve())
    save_report(output, report)
    passed = sum(result["passed"] for result in report["results"])
    errors = sum(result["status"] == "error" for result in report["results"])
    print(f"Recalcul hors ligne : {passed}/{len(report['results']) - errors} réponses évaluables, "
          f"{errors} indisponible(s).")
    if not report["complete"]:
        print("Exécution d'origine incomplète : seuls les cas enregistrés ont été recalculés.")
    print(f"Résultats : {output}")
    return 0 if report["complete"] and report["results"] and not errors and all(
        result["passed"] for result in report["results"]
    ) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--projects-dir", type=Path, help="Directory holding reference checkouts.")
    options = parser.parse_args()
    sys.exit(main(options.report, projects_dir=options.projects_dir))
