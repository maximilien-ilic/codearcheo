"""Persistence: everything learn-it writes lives in `<project>/.learn-it/`, ignored by git."""

from __future__ import annotations

import gzip
import json
import os
import re
import tempfile
import zlib
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from learn_it import git
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

    def _prepare_write(self, name: str) -> Path:
        path = self._path(name)
        self.dir.mkdir(exist_ok=True)
        # An existing output directory also needs the ignore rule.
        self._path(".gitignore").write_text("# Created by learn-it\n*\n", encoding="utf-8")
        return path

    def _write(self, name: str, content: str) -> Path:
        path = self._prepare_write(name)
        path.write_text(content, encoding="utf-8")
        return path

    def save_profile(self, profile: ProjectProfile) -> Path:
        text = profile.model_dump_json(indent=2)
        path = self._write("profile.json", text)
        if profile.head and not profile.uncommitted and self.matches_clean_head(profile.head):
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
        if head and self.matches_clean_head(head):
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

    def matches_clean_head(self, sha: str) -> bool:
        root = self.dir.parent
        try:
            return git.head(root) == sha and not git.run(root, "status", "--porcelain").strip()
        except (git.GitError, OSError):
            return False

    def _snapshot(self, sha: str, name: str, content: str) -> None:
        path = self._snapshot_path(sha, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, filename = tempfile.mkstemp(dir=path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            with suppress(FileExistsError):
                os.link(temporary, path)  # Install complete JSON without replacing prior analysis.
        finally:
            temporary.unlink(missing_ok=True)

    def history_profile(self, sha: str) -> ProjectProfile | None:
        path = self._snapshot_path(sha, "profile.json")
        try:
            return ProjectProfile.model_validate_json(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError, UnicodeError):
            return None

    def history_decisions(self, sha: str) -> list[Decision] | None:
        path = self._snapshot_path(sha, "decisions.json")
        try:
            return _decisions.validate_json(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValidationError, UnicodeError):
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

    def load_json(self, name: str, *, max_bytes: int | None = None) -> Any:
        """A cache file, or None when it is missing or unreadable."""
        try:
            path = self._path(name)
            if max_bytes is None:
                return json.loads(path.read_text(encoding="utf-8"))
            with path.open("rb") as stream:
                data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
            text = data.decode("utf-8")
            del data
            return json.loads(text)
        except (FileNotFoundError, ValueError, RecursionError):
            return None

    def save_json(self, name: str, data: Any) -> Path:
        return self._write(name, json.dumps(data, ensure_ascii=False))

    def load_compressed_json(self, name: str, *, max_bytes: int) -> Any:
        """Read derived gzip data within a decompressed byte limit; corrupt data is a miss."""
        try:
            with gzip.open(self._path(name), "rb") as stream:
                data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
            text = data.decode("utf-8")
            del data
            return json.loads(text)
        except (
            FileNotFoundError, ValueError, EOFError, RecursionError, gzip.BadGzipFile, zlib.error,
        ):
            return None

    def save_compressed_json(
        self, name: str, data: Any, *, max_bytes: int | None = None,
    ) -> Path:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if max_bytes is not None and len(encoded) > max_bytes:
            raise OSError("Compressed JSON exceeds the decompressed byte limit.")
        compressed = gzip.compress(encoded, compresslevel=1, mtime=0)
        path = self._prepare_write(name)
        descriptor, filename = tempfile.mkstemp(dir=path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(compressed)
            temporary.replace(self._path(name))
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def remove(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

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
