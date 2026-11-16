"""Persistence: everything learn-it writes lives in `<project>/.learn-it/`, ignored by git."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from learn_it.domain import Decision, ProjectProfile, Recommendation

_decisions = TypeAdapter(list[Decision])
_recommendations = TypeAdapter(list[Recommendation])


class Store:
    def __init__(self, project_root: Path) -> None:
        self.dir = project_root / ".learn-it"

    def _path(self, name: str) -> Path:
        if not name or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("A stored file must have a plain filename.")
        path = self.dir / name
        if self.dir.is_symlink() or path.is_symlink():
            raise OSError(f"Refusing a symlink in the report store: {path}")
        return path

    def _write(self, name: str, content: str) -> Path:
        path = self._path(name)
        self.dir.mkdir(exist_ok=True)
        # An existing output directory also needs the ignore rule.
        self._path(".gitignore").write_text("# Created by learn-it\n*\n", encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        return path

    def save_profile(self, profile: ProjectProfile) -> Path:
        text = profile.model_dump_json(indent=2)
        path = self._write("profile.json", text)
        if profile.head and not profile.uncommitted:
            self._snapshot(profile.head, "profile.json", text)
        return path

    def load_profile(self) -> ProjectProfile | None:
        path = self._path("profile.json")
        try:
            return ProjectProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError):  # never scanned, or by an older version
            return None

    def save_decisions(self, decisions: list[Decision], *, head: str | None = None) -> Path:
        text = _decisions.dump_json(decisions, indent=2).decode()
        path = self._write("decisions.json", text)
        if head:
            self._snapshot(head, "decisions.json", text)
        return path

    def _snapshot_path(self, sha: str, name: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise ValueError("L'historique exige un SHA complet.")
        history = self._path("history")
        folder = history / sha
        path = folder / name
        if folder.is_symlink() or path.is_symlink():
            raise OSError("Lien symbolique dans l'historique learn-it.")
        return path

    def _snapshot(self, sha: str, name: str, content: str) -> None:
        path = self._snapshot_path(sha, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as output:
                output.write(content)
        except FileExistsError:
            pass  # Preserve the first complete analysis for this revision.

    def history_profile(self, sha: str) -> ProjectProfile | None:
        path = self._snapshot_path(sha, "profile.json")
        try:
            return ProjectProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def history_decisions(self, sha: str) -> list[Decision] | None:
        path = self._snapshot_path(sha, "decisions.json")
        try:
            return _decisions.validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def latest_history(self, *, excluding: str | None = None) -> str | None:
        history = self._path("history")
        if not history.exists():
            return None
        candidates = []
        for folder in history.iterdir():
            if folder.name == excluding or not re.fullmatch(r"[0-9a-f]{40,64}", folder.name):
                continue
            path = self._snapshot_path(folder.name, "profile.json")
            if path.is_file():
                candidates.append((path.stat().st_mtime_ns, folder.name))
        return max(candidates)[1] if candidates else None

    def load_decisions(self) -> list[Decision]:
        path = self._path("decisions.json")
        try:
            return _decisions.validate_json(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError):
            return []

    def save_report(self, name: str, markdown: str) -> Path:
        return self._write(f"{name}.md", markdown)

    def save_recommendations(self, recommendations: list[Recommendation]) -> Path:
        text = _recommendations.dump_json(recommendations, indent=2).decode()
        return self._write("review.json", text)

    def load_recommendations(self) -> list[Recommendation]:
        try:
            return _recommendations.validate_json(self._path("review.json").read_text())
        except (FileNotFoundError, ValidationError):
            return []
