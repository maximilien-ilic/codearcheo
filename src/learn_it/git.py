"""Minimal git wrapper. Arguments reach git as a list, never through a shell."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git command failed."""


def run(root: Path, *args: str, ok: tuple[int, ...] = (0,)) -> str:
    """Run `git <args>` inside `root` and return its stdout.

    Raise GitError when the exit code is not in `ok` (git grep exits 1 on "no match").
    """
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode not in ok:
        raise GitError(proc.stderr.strip() or f"git {args[0]} exited with {proc.returncode}")
    return proc.stdout


def is_repo(root: Path) -> bool:
    try:
        return run(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except (GitError, FileNotFoundError):  # not a repository, or git is not installed
        return False


def head(root: Path) -> str | None:
    try:
        return run(root, "rev-parse", "HEAD").strip()
    except (GitError, FileNotFoundError):  # not a repository, or no commit yet
        return None
