"""Export reconstructed decisions as versionable MADR files inside the project."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from learn_it.analyzers.inventory import is_safe_path
from learn_it.domain import Decision

_NUMBER = re.compile(r"^(\d+)[-_.]")


def _slug(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:100] or "decision"


def madr(decision: Decision, number: int) -> str:
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
    return "\n".join(lines)


def export_decisions(
    root: Path, decisions: list[Decision], directory: Path, *, force: bool = False
) -> list[Path]:
    root = root.resolve()
    target = directory if directory.is_absolute() else root / directory
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("L'export ADR doit rester dans le projet.") from exc
    if not is_safe_path(root, rel):
        raise OSError("Le dossier d'export contient un lien ou un chemin interdit.")
    slugs = [_slug(d.title) for d in decisions]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Plusieurs décisions produisent le même nom de fichier ADR.")
    existing = sorted(target.glob("*.md")) if target.exists() else []
    numbers = [int(m[1]) for file in existing if (m := _NUMBER.match(file.name))]
    next_number = max(numbers, default=0) + 1
    plan = []
    for decision, slug in zip(decisions, slugs, strict=True):
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
        plan.append((path, madr(decision, number)))
    # Validate the entire batch before touching existing files.
    if plan:
        target.mkdir(parents=True, exist_ok=True)
    for path, content in plan:
        with path.open("w" if force else "x", encoding="utf-8") as output:
            output.write(content)
    return [path for path, _ in plan]
