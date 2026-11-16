"""Deterministic review reports and opt-in GitHub issue publication."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from learn_it import git
from learn_it.domain import Recommendation
from learn_it.sources import Project, parse_github


def ordered(items: list[Recommendation]) -> list[Recommendation]:
    impact = {"high": 0, "medium": 1, "low": 2}
    effort = {"S": 0, "M": 1, "L": 2}
    return sorted(items, key=lambda r: (impact[r.impact], effort[r.effort], r.title.casefold()))


def item_markdown(item: Recommendation) -> str:
    lines = [
        f"## {item.title}", "", f"Décision : {item.decision}", "",
        f"Verdict : **{item.verdict}** · impact **{item.impact}** · effort **{item.effort}**", "",
        "### Raisons", "", *(f"- {x}" for x in item.reasons), "",
    ]
    if item.proposal:
        lines += ["### Proposition", "", item.proposal, ""]
    if item.tradeoffs:
        lines += ["### Compromis", "", *(f"- {x}" for x in item.tradeoffs), ""]
    if item.first_steps:
        lines += ["### Tâches", "", *(f"- [ ] {x}" for x in item.first_steps), ""]
    lines += ["### Preuves", "", *(f"- {x}" for x in item.evidence), ""]
    return "\n".join(lines)


def markdown(items: list[Recommendation], synthesis: str) -> str:
    return "\n\n".join([
        "# Revue des décisions", synthesis.strip(), *(item_markdown(r) for r in ordered(items))
    ])


def _marker(item: Recommendation) -> str:
    identity = f"{item.decision.strip().casefold()}\n{item.title.strip().casefold()}"
    key = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return f"<!-- learn-it:recommendation:{key} -->"


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
    with tempfile.TemporaryDirectory(prefix="learn-it-issues-") as temporary:
        for item in candidates:
            marker = _marker(item)
            previous = next((x for x in existing if marker in (x.get("body") or "")), None)
            if previous:
                urls.append(previous["url"])
                continue
            body = Path(temporary) / "body.md"
            body.write_text(f"{marker}\n\n{item_markdown(item)}\n", encoding="utf-8")
            url = _gh(
                "issue", "create", "--repo", repo, "--title", item.title,
                "--body-file", str(body),
            ).strip()
            urls.append(url)
            existing.append({"body": marker, "url": url})
    return urls
