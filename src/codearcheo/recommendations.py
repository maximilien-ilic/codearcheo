"""Deterministic review reports and opt-in GitHub issue publication."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import tempfile
from pathlib import Path
from textwrap import indent

from codearcheo import evidence, git
from codearcheo.domain import Recommendation
from codearcheo.sources import Project, parse_github

_LEADING_FENCE = re.compile(
    r" {0,3}(?:>[ \t]{0,4}|(?:[-+*]|[0-9]{1,9}[.)])[ \t]{1,7})*"
    r"(?:`{3,}[^`\r\n]*|~{3,}[^\r\n]*)(?:\r?\n|$)"
)


def ordered(items: list[Recommendation]) -> list[Recommendation]:
    impact = {"high": 0, "medium": 1, "low": 2}
    effort = {"S": 0, "M": 1, "L": 2}
    return sorted(items, key=lambda r: (impact[r.impact], effort[r.effort], r.title.casefold()))


def item_markdown(item: Recommendation) -> str:
    lines = [
        evidence.close_open_fence(f"## {item.title}"), "",
        evidence.close_open_fence(f"Décision : {item.decision}"), "",
        f"Verdict : **{item.verdict}** · impact **{item.impact}** · effort **{item.effort}**", "",
        "### Raisons", "", *_markdown_items(item.reasons), "",
    ]
    if item.proposal:
        lines += ["### Proposition", "", evidence.close_open_fence(item.proposal), ""]
    if item.tradeoffs:
        lines += ["### Compromis", "", *_markdown_items(item.tradeoffs), ""]
    if item.first_steps:
        lines += ["### Tâches", "", *_markdown_items(item.first_steps, checklist=True), ""]
    lines += ["### Preuves", "", *_markdown_items(item.evidence), ""]
    return "\n".join(lines)


def _markdown_items(items: list[str], *, checklist: bool = False) -> list[str]:
    prefix = "- [ ] " if checklist else "- "
    rendered = []
    for item in items:
        content = evidence.close_open_fence(item)
        if checklist and _LEADING_FENCE.match(content):
            # A task marker would turn the opening fence and its containers into text.
            # A four-column offset preserves Markdown's tab stops inside the example.
            rendered.append(f"-   [ ] Exemple\n{indent(content, '    ')}")
        elif content.startswith((" ", "\t")):
            # Leading whitespace must not change the continuation indentation.
            rendered.append(f"{prefix.rstrip()}\n{indent(content, '  ')}")
        else:
            first, newline, rest = content.partition("\n")
            rendered.append(f"{prefix}{first}{newline}{indent(rest, '  ')}")
    return rendered


def _checked_item_markdown(root: Path, item: Recommendation) -> str:
    # A fence in one field must not hide a citation in another field or list item.
    fields = [
        f"## {item.title}", f"Décision : {item.decision}", *item.reasons, item.proposal,
        *item.tradeoffs, *item.first_steps,
    ]
    citations = [
        citation for text in fields
        for citation in evidence.find_citations(text, respect_quote_boundaries=True)
    ]
    for entry in item.evidence:
        citations.extend(
            evidence.find_citations(entry, respect_quote_boundaries=True)
            or [evidence.Citation(ref=entry)]
        )
    report = evidence.verify_citations(citations, root)
    body = item_markdown(item)
    if report.problems:
        lines = [body, "### Preuves non vérifiées", ""]
        for citation, problem in report.problems.items():
            # Render arbitrary unrecognized evidence as literal, single-line text.
            ref = html.escape(citation.ref, quote=False).replace("`", "&#96;")
            ref = ref.replace("\r", " ").replace("\n", " ")
            lines.append(f"- <code>{ref}</code> : {problem}")
        body = "\n".join(lines) + "\n"
    return body


def markdown(items: list[Recommendation], synthesis: str) -> str:
    return "\n\n".join([
        "# Revue des décisions", evidence.close_open_fence(synthesis.strip()),
        *(item_markdown(r) for r in ordered(items)),
    ])


def _marker(item: Recommendation, *, namespace: str = "codearcheo") -> str:
    identity = f"{item.decision.strip().casefold()}\n{item.title.strip().casefold()}"
    key = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return f"<!-- {namespace}:recommendation:{key} -->"


def _gh(*args: str) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise OSError(proc.stderr.strip() or "Échec de GitHub CLI.")
    return proc.stdout


def publish(project: Project, items: list[Recommendation], *, confirmed: bool = False) -> list[str]:
    if not confirmed:
        raise ValueError("La publication exige une confirmation explicite.")
    origin = project.origin
    if not origin:
        origin = git.run(project.root, "remote", "get-url", "origin").strip()
    names = parse_github(origin)
    if not names:
        raise ValueError("Le projet doit avoir une origine GitHub valide.")
    repo = "/".join(names)
    candidates = [r for r in ordered(items) if r.verdict != "keep"]
    if not candidates:
        return []
    # Reuse even a closed issue: regenerating a report must not recreate completed tasks.
    existing = json.loads(_gh(
        "issue", "list", "--repo", repo, "--state", "all", "--limit", "1000",
        "--json", "body,url",
    ))
    if len(existing) >= 1000:
        raise ValueError("Trop de tickets pour garantir la déduplication : publication annulée.")
    urls = []
    with tempfile.TemporaryDirectory(prefix="codearcheo-issues-") as temporary:
        for item in candidates:
            marker = _marker(item)
            legacy_marker = _marker(item, namespace="learn-it")
            previous = next(
                (issue for issue in existing if any(
                    candidate in (issue.get("body") or "")
                    for candidate in (marker, legacy_marker)
                )),
                None,
            )
            if previous:
                urls.append(previous["url"])
                continue
            body = Path(temporary) / "body.md"
            body.write_text(
                f"{marker}\n\n{_checked_item_markdown(project.root, item)}\n", encoding="utf-8",
            )
            url = _gh(
                "issue", "create", "--repo", repo, "--title", item.title,
                "--body-file", str(body),
            ).strip()
            urls.append(url)
            existing.append({"body": marker, "url": url})
    return urls
