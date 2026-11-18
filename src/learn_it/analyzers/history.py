"""What git history says: activity, hotspots, recent work, and when each technology arrived."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath

from learn_it import git
from learn_it.domain import Commit, Hotspot, Technology

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


def date_technologies(root: Path, technologies: list[Technology]) -> dict[str, str]:
    """Date every notable technology with one patch-history read per source manifest.

    Pickaxe -S tests whether a literal's occurrence count changes. Counting additions minus
    removals in each complete patch gives the same test for our single-line literals, while
    avoiding one full history traversal per dependency. Keep first_commit as the independent
    reference implementation (and for arbitrary multiline needles).

    Return the commit that created each source manifest, for trace_migrations.
    """
    created_by: dict[str, str] = {}
    sources: dict[str, list[Technology]] = {}
    for tech in technologies:
        if tech.category != "library":
            sources.setdefault(tech.source, []).append(tech)
    for path, group in sources.items():
        for tech in group:
            tech.adopted = None
        try:
            # Anchor NUL-delimited headers to output lines below rather than trusting an
            # arbitrary control character in patch data. No external diff/textconv executes.
            out = git.run(
                root, "log", "-p", "--no-color", "--no-show-signature", "--no-ext-diff",
                "--no-textconv", "--no-renames",
                "--format=%x00%H%x1f%an%x1f%aI%x1f%s", "--", path,
            )
        except git.GitError:
            continue
        # A repository can force binary files to be shown as text via .gitattributes.
        # In patches every content line has a diff prefix, so only an actual record
        # boundary starts with NUL + commit id at the beginning of an output line.
        records = re.split(r"(?:^|\n)\x00(?=[0-9a-f]{40}\x1f)", out)[1:]
        for record in records:
            header, _, patch = record.partition("\n")
            sha, author, date, subject = header.split(_SEP, 3)
            commit = Commit(sha=sha, author=author, date=datetime.fromisoformat(date),
                            subject=subject)
            added, removed = [], []
            created = False
            in_hunk = False
            for line in patch.split("\n"):
                if line.startswith("diff --git "):
                    in_hunk = False
                elif line.startswith("new file mode "):
                    created = True
                    created_by[path] = sha  # newest-first: the oldest creation is kept
                elif line.startswith("@@"):
                    in_hunk = True
                elif in_hunk and line.startswith("+"):
                    added.append(line[1:])
                elif in_hunk and line.startswith("-"):
                    removed.append(line[1:])
            additions, removals = "\n".join(added), "\n".join(removed)
            for tech in group:
                needle = tech.needle
                if (not needle and created) or (
                    needle and "\n" not in needle
                    and additions.count(needle) != removals.count(needle)
                ):
                    # Log is newest-first, just like first_commit: last match wins.
                    tech.adopted = commit
        for tech in group:
            if tech.needle and "\n" in tech.needle:
                tech.adopted = first_commit(root, path, tech.needle)
    return created_by


# Manifests a project commonly migrates away from: where a dependency may have lived before.
_LEGACY = re.compile(
    r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg|Pipfile|requirements[^/]*\.txt"
    r"|package\.json|Cargo\.toml"
    r"|go\.mod|pom\.xml|build\.gradle(\.kts)?|Gemfile|composer\.json)$"
)


def _changes(root: Path, sha: str) -> list[tuple[str, str, str]]:
    """(status, old path, new path) of every file a commit touched, renames detected."""
    try:
        out = git.run(root, "show", "--no-color", "--format=", "--name-status", "-M", "-z", sha)
    except git.GitError:
        return []
    fields, changes, i = out.split("\0"), [], 0
    while i < len(fields) and fields[i]:
        status = fields[i][0]
        if status in "RC":
            changes.append((status, fields[i + 1], fields[i + 2]))
            i += 3
        else:
            changes.append((status, fields[i + 1], fields[i + 1]))
            i += 2
    return changes


def trace_migrations(
    root: Path, technologies: list[Technology], created_by: dict[str, str], max_hops: int = 3
) -> None:
    """Follow a dependency back through the manifests its current one replaced.

    When a dependency seems adopted by the very commit that created its manifest (a switch
    from setup.py to pyproject.toml, a moved package.json), the real adoption is earlier: look
    for the dependency in the manifests that commit deleted, renamed or rewrote.
    """
    changes: dict[str, list[tuple[str, str, str]]] = {}
    manifests: dict[tuple[str, str], str] = {}

    def contents(revision: str, path: str) -> str:
        key = revision, path
        if key not in manifests:
            try:
                manifests[key] = git.run(root, "show", "--no-textconv", f"{revision}:{path}")
            except git.GitError:
                manifests[key] = ""
        return manifests[key]

    for tech in technologies:
        if tech.category == "library" or tech.adopted is None or not tech.needle:
            continue
        # Only a dependency manifest can replace an older one, and only when it was created
        # by the adopting commit: otherwise no extra git call is spent on this technology.
        if not _LEGACY.search(tech.source):
            continue
        if created_by.get(tech.source) != tech.adopted.sha:
            continue
        commit, path = tech.adopted, tech.source
        for _ in range(max_hops):
            if commit.sha not in changes:
                changes[commit.sha] = _changes(root, commit.sha)
            touched = changes[commit.sha]
            if not any(new == path and status in "ARC" for status, _, new in touched):
                break  # the manifest already existed: this commit really adopted it
            # A rename to another path can leave the dependency in that other manifest.
            legacy = {
                old for status, old, new in touched
                if old != path and status in "DMR" and _LEGACY.search(old)
                and tech.needle in contents(f"{commit.sha}^", old)
                and (status == "D" or new == path or tech.needle not in contents(commit.sha, new))
            }
            earlier = []
            for candidate in legacy:
                try:
                    out = git.run(root, "log", f"-S{tech.needle}", _FORMAT, f"{commit.sha}^",
                                  "--", candidate)
                except git.GitError:  # root commit: nothing before it
                    continue
                if found := _parse(out):
                    earlier.append((found[-1], candidate))
            if not earlier:
                break
            commit, path = min(earlier, key=lambda item: (item[0].date, item[1]))
            tech.adopted, tech.adopted_from = commit, path


def activity(root: Path) -> tuple[int, int, datetime | None]:
    """Number of commits, number of contributors, date of the first commit."""
    try:
        # One walk replaces rev-list --count, shortlog, root discovery and a command per
        # root. %aN applies .mailmap, as shortlog does; parentless commits give root dates.
        fields = git.run(root, "log", "--format=%aN%x00%aI%x00%P%x00", "HEAD").split("\0")
        records = [fields[i:i + 3] for i in range(0, len(fields) - 1, 3)]
        count = len(records)
        contributors = len({author.removeprefix("\n") for author, _, _ in records})
        first = min(datetime.fromisoformat(date) for _, date, parents in records if not parents)
    except git.GitError:  # no commit yet
        return 0, 0, None
    return count, contributors, first


def uncommitted(root: Path, limit: int = 50) -> list[str]:
    """Paths with uncommitted changes: what the team is working on right now."""
    out = git.run(root, "status", "--porcelain")
    return [line[3:].split(" -> ")[-1] for line in out.splitlines() if line][:limit]
