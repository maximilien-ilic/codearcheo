"""Export reconstructed decisions as versionable MADR files inside the project."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from learn_it import evidence
from learn_it.analyzers.inventory import is_safe_path
from learn_it.domain import Decision

_NUMBER = re.compile(r"^(\d+)[-_.]")


def _slug(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:100] or "decision"


def check_evidence(root: Path, decision: Decision) -> evidence.EvidenceReport:
    """The record's evidence, plus the commit said to introduce it, checked in the project."""
    citations = []
    for item in decision.evidence:
        citations.extend(evidence.find_citations(item) or [evidence.Citation(ref=item)])
    if decision.introduced_in:
        sha = decision.introduced_in
        ref = f"commit {sha}"
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):
            citations.append(evidence.Citation(ref=ref, sha=sha.lower()))
        else:
            citations.append(evidence.Citation(ref=ref))
    return evidence.verify_citations(citations, root)


def madr(decision: Decision, number: int, report: evidence.EvidenceReport | None = None) -> str:
    source = "documentée" if decision.rationale_source == "documented" else "déduite"
    lines = [
        f"# {number:04d}. {decision.title}", "", "- Statut : proposée (à confirmer)", "",
        f"*Reconstituée par learn-it ; justification {source}. Vérifier avant adoption.*", "",
        "## Contexte", "", decision.context, "",
        "## Décision", "", decision.decision, "",
        "## Justification", "", decision.rationale, "",
    ]
    if decision.alternatives:
        lines += ["## Alternatives", "", *(f"- {x}" for x in decision.alternatives), ""]
    lines += ["## Conséquences", "", *(f"- {x}" for x in decision.consequences), ""]
    lines += ["## Preuves", "", *(f"- {x}" for x in decision.evidence), ""]
    if decision.introduced_in:
        lines += [f"Introduite dans le commit {decision.introduced_in}.", ""]
    if report is not None and report.problems:
        problems = report.problems.items()
        lines += ["## Preuves non vérifiées", "",
                  *(f"- {citation.ref} : {problem}" for citation, problem in problems), ""]
    elif report is not None and not report.citations:
        lines += ["## Preuves non vérifiées", "", evidence.summary(report), ""]
    return "\n".join(lines)


def export_decisions(
    root: Path, decisions: list[Decision], directory: Path, *, force: bool = False,
    allow_unproven: bool = False,
) -> list[Path]:
    """Write one MADR file per decision. A decision none of whose evidence checks out is
    refused unless `allow_unproven`: a versioned ADR must not rest on invented sources."""
    root = root.resolve()
    target = directory if directory.is_absolute() else root / directory
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("L'export ADR doit rester dans le projet.") from exc
    if not is_safe_path(root, rel):
        raise OSError("Le dossier d'export contient un lien ou un chemin interdit.")
    reports = [check_evidence(root, d) for d in decisions]
    unproven = [d.title for d, r in zip(decisions, reports, strict=True)
                if len(r.problems) == len(r.citations)]
    if unproven and not allow_unproven:
        raise ValueError(
            "Aucune preuve vérifiable pour : " + " ; ".join(unproven)
            + ". Relancer `decisions`, ou exporter quand même avec --allow-unproven."
        )
    slugs = [_slug(d.title) for d in decisions]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Plusieurs décisions produisent le même nom de fichier ADR.")
    existing = sorted(target.glob("*.md")) if target.exists() else []
    numbers = [int(m[1]) for file in existing if (m := _NUMBER.match(file.name))]
    next_number = max(numbers, default=0) + 1
    plan = []
    for decision, slug, report in zip(decisions, slugs, reports, strict=True):
        matches = [
            file for file in existing
            if (prefix := _NUMBER.match(file.name))
            and file.name[prefix.end():] == f"{slug}.md"
        ]
        if matches:
            if len(matches) > 1:
                raise ValueError(f"Plusieurs ADR existants correspondent à {decision.title!r}.")
            path = matches[0]
            if not force:
                raise FileExistsError(f"ADR existant : {path}. Utiliser --force pour le remplacer.")
            number_match = _NUMBER.match(path.name)
            if not number_match:
                raise ValueError(f"ADR existant sans numéro : {path}")
            number = int(number_match[1])
        else:
            number = next_number
            next_number += 1
            path = target / f"{number:04d}-{slug}.md"
        if not is_safe_path(root, path.relative_to(root).as_posix()):
            raise OSError(f"Lien symbolique ou chemin interdit : {path}")
        if path.exists() and not force:
            raise FileExistsError(path)
        # Check prose too, without treating its valid citations as declared evidence.
        body_problems = evidence.verify(madr(decision, number), root).problems
        report = evidence.EvidenceReport(
            citations=list(dict.fromkeys([*report.citations, *body_problems])),
            problems={**report.problems, **body_problems},
        )
        plan.append((path, madr(decision, number, report)))
    # Validate the entire batch before touching existing files.
    if plan:
        target.mkdir(parents=True, exist_ok=True)
    for path, content in plan:
        with path.open("w" if force else "x", encoding="utf-8") as output:
            output.write(content)
    return [path for path, _ in plan]
