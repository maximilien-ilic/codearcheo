"""Check the evidence an answer cites: every `path:line` and every commit must exist.

codearcheo asks Claude to cite code as `path/to/file.py:12-30` and history as `commit abc1234`
(agent/prompts.py). This module finds those citations and checks them against the project,
so a hallucinated reference gets caught instead of trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from codearcheo import git
from codearcheo.analyzers import inventory

_FILE = re.compile(r"`(?P<path>[^`\r\n:]+):(?P<start>\d+)(?:\s*[-–]\s*(?P<end>\d+))?`")
# Consume each run of backticks whole. Only a run of the opening width closes the span.
_INLINE_CODE = re.compile(
    r"(?<!`)(`++)(?:[^`\r\n]++|(?!\1(?!`))`++|(?>\r\n?|\n)(?![ \t]*[\r\n]))*+\1(?!`)"
)
_ATX_HEADING = re.compile(r"(?<![^\r\n])(?P<prefix>[ \t>]*+)#{1,6}(?=[ \t\r\n]|$)[^\r\n]*")
_HEADING_PREFIX = re.compile(r"(?: {0,3}> ?+)*+ {0,3}")
_QUOTE_PREFIX = re.compile(r"(?:[ \t]*>)*")
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


def find_citations(text: str, *, respect_quote_boundaries: bool = False) -> list[Citation]:
    matches = find_matches(text, respect_quote_boundaries=respect_quote_boundaries)
    return list(dict.fromkeys(match.citation for match in matches))


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


def _fences(
    text: str, *, respect_quote_boundaries: bool = False,
) -> tuple[list[tuple[int, int]], str]:
    """Protect complete and unclosed Markdown fences, including nested list/quote examples.

    A shorter run of backticks inside a longer fence is code, not a closing fence. Treating
    indented examples conservatively as code also prevents edits to embedded diagrams.
    """
    spans = []
    start, marker, width, offset = None, "", 0, 0
    quote_depth = 0
    for line in text.splitlines(keepends=True):
        prefix = _QUOTE_PREFIX.match(line)[0] if respect_quote_boundaries else ""
        depth = prefix.count(">")
        body = line[len(prefix):].lstrip(" \t" if respect_quote_boundaries else " \t>")
        if start is not None and depth < quote_depth:
            spans.append((start, offset))
            start = None
        if start is None:
            body = re.sub(r"^(?:[-+*]|\d+[.)])[ \t]+", "", body)
            opening = re.match(r"(`{3,}|~{3,})([^\r\n]*)(?:\r?\n)?$", body)
            if opening and not (opening[1][0] == "`" and "`" in opening[2]):
                start, marker, width = offset, opening[1][0], len(opening[1])
                quote_depth = depth
        elif depth == quote_depth and re.fullmatch(
            rf"{re.escape(marker)}{{{width},}}[ \t]*(?:\r?\n)?", body,
        ):
            spans.append((start, offset + len(line)))
            start = None
        offset += len(line)
    if start is None:
        return spans, ""
    # A quote or list can end a nested fence implicitly. Only repair top-level fences.
    top_level = re.match(r" {0,3}[`~]", text[start:start + 4])
    return [*spans, (start, len(text))], marker * width if top_level else ""


def fenced_spans(text: str) -> list[tuple[int, int]]:
    return _fences(text)[0]


def close_open_fence(text: str) -> str:
    """Terminate a field's code block before appending other Markdown sections."""
    _, closing = _fences(text, respect_quote_boundaries=True)
    if not closing:
        return text
    separator = "" if text.endswith("\n") else "\n"
    return text + separator + closing


def _inline_code_spans(text: str, protected: list[tuple[int, int]]) -> list[re.Match[str]]:
    # Keep inline code within its Markdown block, including citations inside headings.
    code_spans = []
    offset = 0
    for start, end in [*protected, (len(text), len(text))]:
        for heading in _ATX_HEADING.finditer(text, offset, start):
            if not _HEADING_PREFIX.fullmatch(heading["prefix"].expandtabs(4)):
                continue
            code_spans.extend(_INLINE_CODE.finditer(text, offset, heading.start()))
            code_spans.extend(_INLINE_CODE.finditer(text, heading.start(), heading.end()))
            offset = heading.end()
        code_spans.extend(_INLINE_CODE.finditer(text, offset, start))
        offset = end
    return code_spans


def find_matches(text: str, *, respect_quote_boundaries: bool = False) -> list[CitationMatch]:
    """Return original citation spans outside fenced source examples and diagrams."""
    protected, _ = _fences(text, respect_quote_boundaries=respect_quote_boundaries)
    code_spans = _inline_code_spans(text, protected)
    explicit = []
    for span in code_spans:
        # Match the citation within its paired delimiters. Keep one backtick at
        # each end so replacements preserve any surrounding backticks.
        extra = len(span[1]) - 1
        if match := _FILE.fullmatch(text, span.start() + extra, span.end() - extra):
            explicit.append(match)
    # Inside an inline code span, only a citation matching the whole span counts.
    bare = [
        match for match in _BARE_FILE.finditer(text)
        if not any(span.start() <= match.start() < span.end() for span in code_spans)
    ]
    matches = [
        CitationMatch(
            start=m.start(), end=m.end(),
            citation=Citation(
                ref=m[0], path=m["path"].removeprefix("./"),
                start=_line_number(m["start"]), end=_line_number(m["end"] or m["start"]),
            ),
        )
        for m in [*explicit, *bare]
        if _source_shaped(m["path"])
    ]
    matches += [
        CitationMatch(m.start(), m.end(), Citation(ref=m[0], sha=m["sha"].lower()))
        for m in _COMMIT.finditer(text)
        if not any(span.start() <= m.start() < span.end() for span in explicit)
    ]
    return [
        match for match in matches
        if not any(match.start < end and match.end > start for start, end in protected)
    ]


def complete_paths(text: str, files: list[str], scope: str | None = None) -> str:
    """Rewrite `timed.py:170` as `src/pkg/timed.py:170` when exactly one project file has
    that name, or when the text itself cites exactly one of the files of that name in full.
    A path suffix (`cmd/dist/test.go:713`, relative to `src/`) is completed the same way.
    With no explicit match in the text, a review's --path can settle a name that only
    one file in the scope has. Other ambiguous names are left alone: guessing would
    make a false citation pass."""
    by_name: dict[str, list[str]] = {}
    for path in files:
        by_name.setdefault(PurePosixPath(path).name, []).append(path)
    allowed = set(files)
    matches = find_matches(text)
    named = {m.citation.path for m in matches if m.citation.path and "/" in m.citation.path}
    named |= {
        span[0][len(span[1]):-len(span[1])].removeprefix("./")
        for span in _inline_code_spans(text, fenced_spans(text))
    }
    parts, last = [], 0
    for match in sorted(matches, key=lambda m: m.start):
        path = match.citation.path
        if not path or path in allowed or match.start < last:
            continue
        if match.citation.ref.lstrip("`").startswith("./"):
            continue
        if "/" in path:
            if path.startswith((".", "/")) or ".." in PurePosixPath(path).parts:
                continue
            candidates = [file for file in files if file.endswith(f"/{path}")]
        else:
            candidates = by_name.get(path, [])
        if len(candidates) > 1:
            explicit = [candidate for candidate in candidates if candidate in named]
            if explicit:
                candidates = explicit
            elif scope:
                candidates = [
                    candidate for candidate in candidates
                    if candidate == scope or candidate.startswith(f"{scope}/")
                ]
        if len(candidates) != 1 or candidates[0] == path:
            continue
        cited = text[match.start:match.end].replace(path, candidates[0], 1)
        if not cited.startswith("`") and not _BARE_FILE.fullmatch(cited):
            cited = f"`{cited}`"
        if cited.startswith("`") and not _FILE.fullmatch(cited):
            continue
        parts += [text[last:match.start], cited]
        last = match.end
    return "".join(parts) + text[last:]


def mentioned_paths(text: str) -> set[str]:
    """Paths written as code spans, with or without lines: `app.py`, `app.py:3`."""
    return {span.split(":", 1)[0].removeprefix("./") for span in _CODE_SPAN.findall(text)}


def verify(text: str, root: Path) -> EvidenceReport:
    return verify_citations(find_citations(text), root)


def verify_citations(citations: list[Citation], root: Path) -> EvidenceReport:
    report = EvidenceReport(list(dict.fromkeys(citations)))
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
    if citation.path is None:
        return "format de référence non reconnu"
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
