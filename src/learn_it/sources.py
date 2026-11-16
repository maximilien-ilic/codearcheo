"""Resolve what to analyse: a local directory, or a GitHub repository cloned into a cache."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from learn_it import git

GITHUB = re.compile(
    r"^(?:(?:https?://)?(?:www\.)?|git@)github\.com[/:]"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?(?:/.*)?$"
)


@dataclass(frozen=True)
class Project:
    root: Path
    name: str
    origin: str | None = None  # GitHub URL when the project comes from GitHub


def parse_github(target: str) -> tuple[str, str] | None:
    """Return (owner, repo) when `target` is a GitHub URL, else None."""
    match = GITHUB.match(target.strip())
    if not match:
        return None
    owner, repo = match["owner"], match["repo"]
    # Both names become directory names and the clone destination becomes a git argument.
    if (
        owner in {".", ".."} or repo in {".", ".."}
        or owner.startswith("-") or repo.startswith("-")
    ):
        return None
    return owner, repo


def resolve(target: str, cache_dir: Path, *, update: bool = False) -> Project:
    """Turn a CLI target into a project on disk.

    GitHub repositories are cloned with their full history, since that is where the "why"
    lives, into `cache_dir/repos/<owner>/<repo>` and reused afterwards. `update` pulls the
    latest commits of an existing clone.
    """
    if github := parse_github(target):
        owner, repo = github
        root = cache_dir / "repos" / owner / repo
        if root.is_symlink() or root.parent.is_symlink() or root.parent.parent.is_symlink():
            raise OSError("Le cache GitHub contient un lien symbolique : clone refusé.")
        if not (root / ".git").exists():
            root.parent.mkdir(parents=True, exist_ok=True)
            git.run(root.parent, "clone", "--quiet", f"https://github.com/{owner}/{repo}.git", repo)
        elif update:
            git.run(root, "pull", "--ff-only", "--quiet")
        return Project(root=root, name=repo, origin=f"https://github.com/{owner}/{repo}")

    if GITHUB.match(target.strip()):
        raise ValueError(f"URL GitHub invalide : {target}")
    root = Path(target).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Dossier introuvable : {target}")
    return Project(root=root, name=root.name)
