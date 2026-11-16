"""Persistence: everything learn-it writes lives in `<project>/.learn-it/`, ignored by git."""

from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from learn_it.domain import Decision, ProjectProfile

_decisions = TypeAdapter(list[Decision])


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
        return self._write("profile.json", profile.model_dump_json(indent=2))

    def load_profile(self) -> ProjectProfile | None:
        path = self._path("profile.json")
        try:
            return ProjectProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError):  # never scanned, or by an older version
            return None

    def save_decisions(self, decisions: list[Decision]) -> Path:
        return self._write("decisions.json", _decisions.dump_json(decisions, indent=2).decode())

    def load_decisions(self) -> list[Decision]:
        path = self._path("decisions.json")
        try:
            return _decisions.validate_json(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError):
            return []

    def save_report(self, name: str, markdown: str) -> Path:
        return self._write(f"{name}.md", markdown)
