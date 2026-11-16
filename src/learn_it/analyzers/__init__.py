"""Deterministic analysis: everything learn-it can establish about a project without an LLM."""

from __future__ import annotations

from typing import Any

from learn_it import git
from learn_it.analyzers import history, inventory, stack
from learn_it.domain import ProjectProfile
from learn_it.sources import Project


def scan(project: Project) -> ProjectProfile:
    root = project.root
    files = inventory.list_files(root)
    technologies = stack.detect(root, files)

    facts: dict[str, Any] = {}
    if git.is_repo(root):
        for tech in technologies:
            if tech.category != "library":  # dating every utility would cost more than it says
                tech.adopted = history.first_commit(root, tech.source, tech.needle)
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

    return ProjectProfile(
        name=project.name,
        origin=project.origin,
        files=len(files),
        languages=inventory.count_languages(files),
        technologies=technologies,
        docs=inventory.find_docs(files),
        **facts,
    )
