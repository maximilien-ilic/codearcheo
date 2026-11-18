"""Deterministic analysis: everything learn-it can establish about a project without an LLM."""

from __future__ import annotations

from typing import Any

from learn_it import git
from learn_it.analyzers import adrs, code, history, inventory, stack
from learn_it.domain import ProjectProfile
from learn_it.sources import Project, github_origin


def scan(project: Project) -> ProjectProfile:
    root = project.root
    files = inventory.list_files(root)
    technologies = stack.detect(root, files)

    facts: dict[str, Any] = {}
    if git.is_repo(root):
        created_by = history.date_technologies(root, technologies)
        history.trace_migrations(root, technologies, created_by)
        commits = history.recent_commits(root)
        count, contributors, first = history.activity(root)
        facts = {
            "head": git.head(root),
            "commits": count,
            "contributors": contributors,
            "first_commit": first,
            "last_commit": commits[0].date if commits else None,
            "hotspots": history.hotspots(commits, set(files)),
            "recent_commits": commits[:10],
            "uncommitted": history.uncommitted(root),
        }

    graph = code.analyze(root, files)
    return ProjectProfile(
        name=project.name,
        origin=project.origin or github_origin(root),
        files=len(files),
        languages=inventory.count_languages(files),
        technologies=technologies,
        docs=inventory.find_docs(files),
        existing_adrs=adrs.detect(root, files),
        code_structure=graph.summary(facts.get("hotspots", ())) if graph is not None else None,
        **facts,
    )
