"""Minimal git wrapper. Arguments reach git as a list, never through a shell."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_environment: ContextVar[Mapping[str, str] | None] = ContextVar("git_environment", default=None)


@contextmanager
def environment(values: Mapping[str, str]) -> Iterator[None]:
    """Scope Git subprocess settings without changing the process environment."""
    token = _environment.set(values)
    try:
        yield
    finally:
        _environment.reset(token)


class GitError(RuntimeError):
    """A git command failed."""


def run(root: Path, *args: str, ok: tuple[int, ...] = (0,)) -> str:
    """Run `git <args>` inside `root` and return its stdout.

    Raise GitError when the exit code is not in `ok` (git grep exits 1 on "no match").
    """
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "log.showSignature=false",
         "-c", "color.ui=false", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_environment.get(),
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
