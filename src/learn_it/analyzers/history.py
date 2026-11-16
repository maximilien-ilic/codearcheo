"""What git history says: activity, hotspots, recent work, and when each technology arrived."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

from learn_it import git
from learn_it.domain import Commit, Hotspot

_SEP, _RECORD = "\x1f", "\x1e"
_FORMAT = f"--format={_RECORD}%H{_SEP}%an{_SEP}%aI{_SEP}%s"
# Files that change all the time without saying anything about the design.
_NOISE = re.compile(
    r"^(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|Cargo\.lock|go\.sum"
    r"|composer\.lock|Gemfile\.lock|(changelog|changes|history|news)(\.\w+)?)$",
    re.IGNORECASE,
)


def _parse(out: str) -> list[Commit]:
    commits = []
    for record in out.split(_RECORD)[1:]:
        header, _, body = record.partition("\n")
        sha, author, date, subject = header.split(_SEP, 3)
        commits.append(
            Commit(
                sha=sha,
                author=author,
                date=datetime.fromisoformat(date),
                subject=subject,
                files=[line for line in body.splitlines() if line],
            )
        )
    return commits


def recent_commits(root: Path, limit: int = 2000) -> list[Commit]:
    """Latest non-merge commits, newest first, with the files each one touched."""
    try:
        out = git.run(
            root, "log", f"-n{limit}", "--no-merges", "--relative", "--name-only", _FORMAT
        )
    except git.GitError:  # no commit yet
        return []
    return _parse(out)


def hotspots(commits: list[Commit], existing: set[str], top: int = 10) -> list[Hotspot]:
    """Files changed most often: where the project's complexity and churn concentrate."""
    counts = Counter(
        f
        for commit in commits
        for f in commit.files
        if f in existing and not _NOISE.match(PurePosixPath(f).name)
    )
    return [Hotspot(path=path, commits=n) for path, n in counts.most_common(top)]


def first_commit(root: Path, path: str, needle: str | None = None) -> Commit | None:
    """Oldest commit that added `needle` to `path` (`git log -S`), or that created `path`."""
    selector = f"-S{needle}" if needle else "--diff-filter=A"
    try:
        commits = _parse(git.run(root, "log", selector, _FORMAT, "--", path))
    except git.GitError:
        return None
    return commits[-1] if commits else None


def activity(root: Path) -> tuple[int, int, datetime | None]:
    """Number of commits, number of contributors, date of the first commit."""
    try:
        count = int(git.run(root, "rev-list", "--count", "HEAD"))
        contributors = len(git.run(root, "shortlog", "-sn", "HEAD").splitlines())
        roots = git.run(root, "rev-list", "--max-parents=0", "HEAD").split()
        first = min(
            datetime.fromisoformat(git.run(root, "log", "-1", "--format=%aI", sha).strip())
            for sha in roots
        )
    except git.GitError:  # no commit yet
        return 0, 0, None
    return count, contributors, first


def uncommitted(root: Path, limit: int = 50) -> list[str]:
    """Paths with uncommitted changes: what the team is working on right now."""
    out = git.run(root, "status", "--porcelain")
    return [line[3:].split(" -> ")[-1] for line in out.splitlines() if line][:limit]
