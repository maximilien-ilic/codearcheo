import pytest

from codearcheo.analyzers import adrs, scan
from codearcheo.domain import Decision
from codearcheo.sources import Project

MADR = """---
status: accepted
date: 2024-03-02
---
# Use SQLite

## Context and Problem Statement
We work without a database server.

## Decision Outcome
Chosen option: SQLite, because users work offline.

## Consequences
One database per workstation.
"""
NYGARD = """# 0002. PostgreSQL

## Status
Accepted

Date: 2023-01-03

## Context
Multiple application instances.

## Decision
Store data in PostgreSQL.

## Consequences
Run a database service.
"""


@pytest.mark.parametrize("text,title,status,date", [
    (MADR, "Use SQLite", "accepted", "2024-03-02"),
    (NYGARD, "PostgreSQL", "Accepted", "2023-01-03"),
])
def test_parses_madr_and_nygard(text, title, status, date):
    record = adrs.parse("docs/adr/0001.md", text)
    assert (record.title, record.status, record.date) == (title, status, date)
    assert record.decision and record.context and record.consequences
    assert record.start_line <= record.end_line <= len(text.splitlines())
    assert "docs/adr/0001.md:" in record.evidence


def test_scan_reads_existing_adrs_but_skips_readmes_and_links(tmp_path):
    folder = tmp_path / "doc" / "decisions"
    folder.mkdir(parents=True)
    (folder / "0001-sqlite.md").write_text(MADR)
    (folder / "README.md").write_text("# ADR index\nThe decisions live here.\n")
    (folder / "0002-link.md").symlink_to(folder / "0001-sqlite.md")
    profile = scan(Project(tmp_path, "app"))
    assert [item.title for item in profile.existing_adrs] == ["Use SQLite"]


def test_existing_documented_rationale_cannot_be_relabelled_inferred():
    record = adrs.parse("docs/adr/0001.md", MADR)
    decision = Decision(
        title="Use SQLite", category="data", context="workstations", decision="SQLite",
        rationale="Users work offline.", rationale_source="inferred", consequences=[], evidence=[],
    )
    anchored = adrs.anchor_decision(decision, [record])
    assert anchored.rationale_source == "documented"
    assert anchored.evidence == [record.evidence]
    unrelated = decision.model_copy(update={"title": "Use PostgreSQL"})
    assert adrs.anchor_decision(unrelated, [record]).rationale_source == "inferred"
    refers_to_old_choice = unrelated.model_copy(update={"evidence": [record.evidence]})
    assert adrs.anchor_decision(refers_to_old_choice, [record]).rationale_source == "inferred"
