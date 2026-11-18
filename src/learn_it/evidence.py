"""Check the evidence an answer cites: every `path:line` and every commit must exist.

learn-it asks Claude to cite code as `path/to/file.py:12-30` and history as `commit abc1234`
(agent/prompts.py). This module finds those citations and checks them against the project,
so a hallucinated reference gets caught instead of trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from learn_it import git
from learn_it.analyzers import inventory

_FILE = re.compile(r"`(?P<path>[^`\s:]+):(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?`")
_BARE_FILE = re.compile(
    r"(?<![\w`/.@+-])(?P<path>(?:[\w.@+-]+/)+[\w.@+-]+|[\w@+-]+\.[\w.-]+"
    r"|\.[\w.-]+|Dockerfile|Makefile|README|LICENSE|Jenkinsfile)"
    r":(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?"
)
_COMMIT = re.compile(r"\bcommits?\s+`?(?P<sha>[0-9a-f]{7,40})\b`?", re.IGNORECASE)
_CODE_SPAN = re.compile(r"`([^`\s]+)`")
_SOURCE_SUFFIXES = set(inventory.LANGUAGES) | {
    ".md", ".mdx", ".rst", ".adoc", ".txt", ".json", ".toml", ".yaml", ".yml",
    ".xml", ".ini", ".cfg", ".conf", ".properties", ".lock", ".gradle", ".csproj",
    ".fsproj", ".vbproj", ".sln", ".proto", ".graphql", ".gql", ".csv", ".tsv",
    ".less", ".pem", ".key", ".p12", ".pfx",
}
_SOURCE_NAMES = {"Dockerfile", "Makefile", "README", "LICENSE", "Jenkinsfile", "Gemfile"}


@dataclass(frozen=True)
class Citation:
    ref: str  # as written in the answer
    path: str | None = None
    start: int = 0
    end: int = 0
    sha: str | None = None


@dataclass(frozen=True)
class CitationMatch:
    """One exact occurrence, so editing a citation cannot also change a longer path."""

    start: int
    end: int
    citation: Citation


@dataclass
class EvidenceReport:
    citations: list[Citation] = field(default_factory=list)
    problems: dict[Citation, str] = field(default_factory=dict)  # why each bad citation fails

    @property
    def ok(self) -> bool:
        """At least one citation, and all of them check out."""
        return bool(self.citations) and not self.problems


def _line_number(value: str) -> int:
    # A model can emit thousands of digits. Keep it invalid without Python's int-size error.
    return int(value) if len(value) <= 10 else 10**11


def find_citations(text: str) -> list[Citation]:
    return list(dict.fromkeys(match.citation for match in find_matches(text)))


def _source_shaped(path: str) -> bool:
    """A dotted host or IP followed by a port must not become editable factual data.

    Bare filenames are inherently ambiguous. Require a familiar source suffix, a known
    manifest name, a hidden project file or a project-relative path. Unknown standalone
    extensions can still be cited with an explicit directory, such as `./schema.custom:1`.
    """
    if "/" in path or "\\" in path:
        return True
    if path.startswith(".") or path in _SOURCE_NAMES:
        return True
    return PurePosixPath(path).suffix.lower() in _SOURCE_SUFFIXES


def fenced_spans(text: str) -> list[tuple[int, int]]:
    """Protect complete and unclosed Markdown fences, including nested list/quote examples.

    A shorter run of backticks inside a longer fence is code, not a closing fence. Treating
    indented examples conservatively as code also prevents edits to embedded diagrams.
    """
    spans = []
    start, marker, width, offset = None, "", 0, 0
    for line in text.splitlines(keepends=True):
        body = line.lstrip(" \t>")
        if start is None:
            body = re.sub(r"^(?:[-+*]|\d+[.)])[ \t]+", "", body)
            opening = re.match(r"(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?$", body)
            if opening and not (opening[1][0] == "`" and "`" in opening[2]):
                start, marker, width = offset, opening[1][0], len(opening[1])
        elif re.fullmatch(rf"{re.escape(marker)}{{{width},}}[ \t]*(?:\r?\n)?", body):
            spans.append((start, offset + len(line)))
            start = None
        offset += len(line)
    if start is not None:
        spans.append((start, len(text)))
    return spans


def find_matches(text: str) -> list[CitationMatch]:
    """Return original citation spans outside fenced source examples and diagrams."""
    matches = [
        CitationMatch(
            start=m.start(), end=m.end(),
            citation=Citation(
                ref=m[0], path=m["path"].removeprefix("./"),
                start=_line_number(m["start"]), end=_line_number(m["end"] or m["start"]),
            ),
        )
        for pattern in (_FILE, _BARE_FILE) for m in pattern.finditer(text)
        if _source_shaped(m["path"])
    ]
    matches += [
        CitationMatch(m.start(), m.end(), Citation(ref=m[0], sha=m["sha"].lower()))
        for m in _COMMIT.finditer(text)
    ]
    protected = fenced_spans(text)
    return [
        match for match in matches
        if not any(match.start < end and match.end > start for start, end in protected)
    ]


def complete_paths(text: str, files: list[str]) -> str:
    """Rewrite `timed.py:170` as `src/pkg/timed.py:170` when exactly one project file has
    that name, or when the text itself cites exactly one of the files of that name in full.
    Other ambiguous names are left alone: guessing would make a false citation pass."""
    by_name: dict[str, list[str]] = {}
    for path in files:
        by_name.setdefault(PurePosixPath(path).name, []).append(path)
    named = {c.path for c in find_citations(text) if c.path and "/" in c.path}
    named |= {span for span in mentioned_paths(text) if "/" in span}
    parts, last = [], 0
    for match in sorted(find_matches(text), key=lambda m: m.start):
        path = match.citation.path
        if not path or "/" in path or match.start < last:
            continue
        candidates = by_name.get(path, [])
        if len(candidates) > 1:
            candidates = [candidate for candidate in candidates if candidate in named]
        if len(candidates) != 1 or candidates[0] == path:
            continue
        cited = text[match.start:match.end].replace(path, candidates[0], 1)
        parts += [text[last:match.start], cited]
        last = match.end
    return "".join(parts) + text[last:]


def mentioned_paths(text: str) -> set[str]:
    """Paths written as code spans, with or without lines: `app.py`, `app.py:3`."""
    return {span.split(":", 1)[0].removeprefix("./") for span in _CODE_SPAN.findall(text)}


def verify(text: str, root: Path) -> EvidenceReport:
    report = EvidenceReport(find_citations(text))
    allowed = set(inventory.list_files(root)) if any(c.path for c in report.citations) else set()
    for citation in report.citations:
        if problem := _problem(citation, root, allowed):
            report.problems[citation] = problem
    return report


def summary(report: EvidenceReport) -> str:
    good = len(report.citations) - len(report.problems)
    if not report.citations:
        return "Aucune citation vérifiable trouvée ; les affirmations restent à vérifier."
    return f"{good} citation(s) vérifiée(s), {len(report.problems)} introuvable(s)."


def markdown_report(report: EvidenceReport) -> str:
    lines = ["---", "", f"> Vérification des sources : {summary(report)}"]
    lines += [f"> - {citation.ref} : {problem}" for citation, problem in report.problems.items()]
    return "\n".join(lines)


def _problem(citation: Citation, root: Path, allowed: set[str]) -> str | None:
    if citation.sha:
        try:
            git.run(root, "cat-file", "-e", f"{citation.sha}^{{commit}}")
        except (git.GitError, FileNotFoundError):
            return "commit introuvable"
        return None
    path = citation.path or ""
    if path not in allowed or not inventory.is_safe_path(root, path) or not (root / path).is_file():
        return "fichier introuvable"
    try:
        full = root / path
        if full.stat().st_size > 5_000_000:
            return "fichier trop volumineux pour vérifier les lignes"
        lines = len(full.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return "fichier illisible"
    if not 1 <= citation.start <= citation.end <= lines:
        return f"lignes hors du fichier ({lines} lignes)"
    return None
