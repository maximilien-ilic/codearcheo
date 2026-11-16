"""Check the evidence an answer cites: every `path:line` and every commit must exist.

learn-it asks Claude to cite code as `path/to/file.py:12-30` and history as `commit abc1234`
(agent/prompts.py). This module finds those citations and checks them against the project,
so a hallucinated reference gets caught instead of trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from learn_it import git
from learn_it.analyzers import inventory

_FILE = re.compile(r"`(?P<path>[^`\s:]+):(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?`")
_COMMIT = re.compile(r"\bcommits?\s+`?(?P<sha>[0-9a-f]{7,40})\b`?", re.IGNORECASE)
_CODE_SPAN = re.compile(r"`([^`\s]+)`")


@dataclass(frozen=True)
class Citation:
    ref: str  # as written in the answer
    path: str | None = None
    start: int = 0
    end: int = 0
    sha: str | None = None


@dataclass
class EvidenceReport:
    citations: list[Citation] = field(default_factory=list)
    problems: dict[Citation, str] = field(default_factory=dict)  # why each bad citation fails

    @property
    def ok(self) -> bool:
        """At least one citation, and all of them check out."""
        return bool(self.citations) and not self.problems


def find_citations(text: str) -> list[Citation]:
    citations = [
        Citation(
            ref=m[0],
            path=m["path"].removeprefix("./"),
            start=int(m["start"]),
            end=int(m["end"] or m["start"]),
        )
        for m in _FILE.finditer(text)
    ]
    citations += [Citation(ref=m[0], sha=m["sha"].lower()) for m in _COMMIT.finditer(text)]
    return list(dict.fromkeys(citations))  # unique, in order of appearance


def mentioned_paths(text: str) -> set[str]:
    """Paths written as code spans, with or without lines: `app.py`, `app.py:3`."""
    return {span.split(":", 1)[0].removeprefix("./") for span in _CODE_SPAN.findall(text)}


def verify(text: str, root: Path) -> EvidenceReport:
    report = EvidenceReport(find_citations(text))
    for citation in report.citations:
        if problem := _problem(citation, root):
            report.problems[citation] = problem
    return report


def _problem(citation: Citation, root: Path) -> str | None:
    if citation.sha:
        try:
            git.run(root, "cat-file", "-e", f"{citation.sha}^{{commit}}")
        except (git.GitError, FileNotFoundError):
            return "commit introuvable"
        return None
    path = citation.path or ""
    if not inventory.is_safe_path(root, path) or not (root / path).is_file():
        return "fichier introuvable"
    lines = len((root / path).read_text(encoding="utf-8", errors="replace").splitlines())
    if not 1 <= citation.start <= citation.end <= lines:
        return f"lignes hors du fichier ({lines} lignes)"
    return None
