"""Deterministic changes between revisions, without checking out the user's worktree."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from learn_it import git
from learn_it.analyzers import scan
from learn_it.domain import Decision, ProjectProfile
from learn_it.sources import Project
from learn_it.store import Store


@dataclass
class Changes:
    before: str
    after: str
    technologies_added: list[str] = field(default_factory=list)
    technologies_removed: list[str] = field(default_factory=list)
    decisions_added: list[str] = field(default_factory=list)
    decisions_removed: list[str] = field(default_factory=list)
    decisions_changed: list[str] = field(default_factory=list)
    decisions_available: bool = False

    def as_dict(self) -> dict:
        return asdict(self)

    def markdown(self) -> str:
        lines = [f"# Changements : {self.before[:12]} → {self.after[:12]}", ""]
        for title, values in (
            ("Technos ajoutées", self.technologies_added),
            ("Technos retirées", self.technologies_removed),
            ("Décisions nouvelles", self.decisions_added),
            ("Décisions modifiées", self.decisions_changed),
            ("Décisions retirées", self.decisions_removed),
        ):
            lines += [f"## {title}", "", *(f"- {x}" for x in values or ["Aucune."]), ""]
        if not self.decisions_available:
            lines += ["Décisions non comparées : une analyse manque pour au moins un des SHA.", ""]
        return "\n".join(lines)


def profile_at(project: Project, sha: str) -> ProjectProfile:
    """Use a disposable shared clone; never execute code or hooks from the target."""
    top = Path(git.run(project.root, "rev-parse", "--show-toplevel").strip()).resolve()
    relative = project.root.resolve().relative_to(top)
    with TemporaryDirectory(prefix="learn-it-diff-") as tmp:
        destination = Path(tmp) / "revision"
        git.run(
            Path(tmp), "-c", "core.hooksPath=/dev/null", "clone", "--quiet",
            "--no-checkout", "--shared", "--", str(top), str(destination),
        )
        git.run(
            destination, "-c", "core.hooksPath=/dev/null", "checkout", "--quiet", "--detach", sha
        )
        root = destination / relative
        if not root.is_dir():
            raise ValueError("Ce dossier n'existait pas dans la révision demandée.")
        return scan(Project(root, project.name, project.origin))


def compare_profiles(
    before: ProjectProfile, after: ProjectProfile,
    old_decisions: list[Decision] | None = None, new_decisions: list[Decision] | None = None,
) -> Changes:
    old = {x.name for x in before.technologies}
    new = {x.name for x in after.technologies}
    changes = Changes(
        before.head or "sans-git", after.head or "travail-en-cours",
        sorted(new - old), sorted(old - new),
    )
    if after.uncommitted:
        changes.after += "+travail-en-cours"
    if old_decisions is not None and new_decisions is not None:
        previous = {d.title: d for d in old_decisions}
        current = {d.title: d for d in new_decisions}
        changes.decisions_available = True
        changes.decisions_added = sorted(current.keys() - previous.keys())
        changes.decisions_removed = sorted(previous.keys() - current.keys())
        changes.decisions_changed = sorted(
            title for title in current.keys() & previous.keys() if current[title] != previous[title]
        )
    return changes


def compare(project: Project, store: Store, ref: str | None = None) -> Changes:
    if not git.is_repo(project.root):
        raise ValueError("learn-it diff exige un projet Git.")
    current = scan(project)
    if not ref:
        ref = store.latest_history(excluding=current.head) or current.head
    if not ref or ref.startswith("-"):
        raise ValueError("Donner une référence Git valide à comparer.")
    sha = git.run(project.root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    sha = sha.strip()
    previous = store.history_profile(sha) or profile_at(project, sha)
    # No generated decision analysis is inferred merely from a change in Git history.
    old_decisions = store.history_decisions(sha)
    new_decisions = store.history_decisions(current.head) if current.head else None
    if current.uncommitted:
        new_decisions = None
    result = compare_profiles(previous, current, old_decisions, new_decisions)
    store.save_profile(current)
    return result
