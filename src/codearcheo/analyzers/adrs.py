"""Read MADR and Nygard decision records as documented facts, without executing Markdown."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from codearcheo.analyzers import inventory
from codearcheo.domain import Decision, ExistingADR

MAX_BYTES = 256_000
MAX_ADRS = 100
_ADR_DIR = re.compile(r"(^|/)(adrs?|decisions)/", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_NUMBER = re.compile(r"^\d+[.)]?\s*")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_METADATA = re.compile(r"^\s*(?:[-*]\s*)?(status|statut|date)\s*:\s*(.+?)\s*$", re.I)
_DECISION = {"decision", "décision", "decision outcome", "résultat de la décision"}
_CONTEXT = {"context", "contexte", "context and problem statement", "contexte et problème"}
_CONSEQUENCES = {"consequences", "conséquences"}


def _label(value: str) -> str:
    return _NUMBER.sub("", value.strip()).strip(" *_").casefold()


def parse(path: str, text: str) -> ExistingADR | None:
    """Recognise a decision section, rather than treating every Markdown document as an ADR."""
    lines = text.splitlines()
    title = None
    status = None
    date = None
    sections: dict[str, tuple[int, int, str]] = {}
    headings = [(index, m) for index, line in enumerate(lines) if (m := _HEADING.match(line))]
    for index, heading in headings:
        if len(heading[1]) == 1 and title is None:
            title = _NUMBER.sub("", heading[2]).strip()
        label = _label(heading[2])
        end = next(
            (n for n, following in headings if n > index and len(following[1]) <= len(heading[1])),
            len(lines),
        )
        body = "\n".join(lines[index + 1:end]).strip()
        sections.setdefault(label, (index + 1, end, body))
    for line in lines:
        if match := _METADATA.match(line):
            value = match[2].strip("'\"")
            if match[1].casefold() in {"status", "statut"} and status is None:
                status = value[:200]
            if match[1].casefold() == "date" and (match_date := _DATE.search(value)):
                date = match_date[0]
    for label in ("status", "statut"):
        if label in sections and not status:
            status = sections[label][2].splitlines()[0][:200] if sections[label][2] else None
    if "date" in sections and not date and (match := _DATE.search(sections["date"][2])):
        date = match[0]
    outcome = next((sections[key] for key in sections if key in _DECISION), None)
    if not title or not outcome or not outcome[2]:
        return None
    context = next((body for key, (_, _, body) in sections.items() if key in _CONTEXT), "")
    consequences = next(
        (body for key, (_, _, body) in sections.items() if key in _CONSEQUENCES), ""
    )
    return ExistingADR(
        title=title, path=path, status=status, date=date, decision=outcome[2][:4000],
        context=context[:2000], consequences=consequences[:2000],
        start_line=outcome[0], end_line=max(outcome[0], outcome[1]),
    )


def detect(root: Path, files: list[str]) -> list[ExistingADR]:
    records = []
    for path in files:
        if len(records) >= MAX_ADRS:
            break
        if not _ADR_DIR.search(path) or PurePosixPath(path).suffix.casefold() not in {
            ".md", ".mdx",
        }:
            continue
        if not inventory.is_safe_path(root, path):
            continue
        try:
            with (root / path).open("rb") as file:
                data = file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                continue
            record = parse(path, data.decode("utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if record:
            records.append(record)
    return records


def anchor_decision(decision: Decision, records: list[ExistingADR]) -> Decision:
    """Keep an already documented decision documented, even if an agent labels it inferred.

    A match requires its normalized title. Citing an old ADR may describe a rejected option,
    so an ADR path in the evidence alone must not relabel an unrelated decision documented.
    This does not claim that the current code still follows the ADR: the agent must check it.
    """
    for record in records:
        if _label(decision.title) == _label(record.title):
            refs = [*decision.evidence]
            if record.evidence not in refs:
                refs.append(record.evidence)
            return decision.model_copy(update={"rationale_source": "documented", "evidence": refs})
    return decision
