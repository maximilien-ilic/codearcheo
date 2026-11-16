"""Measure scan stages and compare the optimized profile with independent full walks.

Run from the repository: uv run python scripts/benchmark_scan.py /path/to/project --compare
No target code or AI API is executed. Clone/fetch time is deliberately outside the timings.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from time import perf_counter

from learn_it import git
from learn_it.analyzers import history, inventory, scan, stack
from learn_it.sources import Project


def reference_dates(root, technologies):
    for technology in technologies:
        if technology.category != "library":
            technology.adopted = history.first_commit(root, technology.source, technology.needle)


def reference_activity(root):
    try:
        count = int(git.run(root, "rev-list", "--count", "HEAD"))
        people = len(git.run(root, "shortlog", "-sn", "HEAD").splitlines())
        roots = git.run(root, "rev-list", "--max-parents=0", "HEAD").split()
        first = min(datetime.fromisoformat(git.run(root, "log", "-1", "--format=%aI", sha).strip())
                    for sha in roots)
    except git.GitError:
        return 0, 0, None
    return count, people, first


def measure(project: Project, *, reference: bool = False):
    stages = {}
    calls = []
    originals = []

    def wrap(owner, attribute, replacement=None):
        original = getattr(owner, attribute)
        originals.append((owner, attribute, original))
        function = replacement or original

        def timed(*args, **kwargs):
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                stages[attribute] = stages.get(attribute, 0.0) + perf_counter() - started

        setattr(owner, attribute, timed)

    original_git = git.run

    def counted(root, *args, **kwargs):
        calls.append(args[0])
        return original_git(root, *args, **kwargs)

    originals.append((git, "run", original_git))
    git.run = counted
    wrap(inventory, "list_files")
    wrap(stack, "detect")
    wrap(history, "date_technologies", reference_dates if reference else None)
    wrap(history, "recent_commits")
    wrap(history, "activity", reference_activity if reference else None)
    wrap(history, "uncommitted")
    started = perf_counter()
    try:
        profile = scan(project)
        return profile, {"seconds": perf_counter() - started, "stages": stages,
                         "git_calls": len(calls)}
    finally:
        for owner, attribute, original in reversed(originals):
            setattr(owner, attribute, original)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error("--runs must be between 1 and 20")
    root = args.project.resolve(strict=True)
    project = Project(root, root.name)
    report = {"optimized": [], "reference": [], "profiles_identical": True}
    for _ in range(args.runs):
        profile, measurement = measure(project)
        report["optimized"].append(measurement)
        if args.compare:
            expected, baseline = measure(project, reference=True)
            report["reference"].append(baseline)
            report["profiles_identical"] &= profile.model_dump() == expected.model_dump()
    report |= {
        "sha": profile.head, "commits": profile.commits, "files": profile.files,
        "optimized_median_seconds": statistics.median(r["seconds"] for r in report["optimized"]),
        "reference_median_seconds": statistics.median(r["seconds"] for r in report["reference"])
        if report["reference"] else None,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["profiles_identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
