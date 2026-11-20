"""Synthetic repository whose SQLite rationale exists only in recorded GitHub PR data."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from codearcheo import github
from evals.shop import _commit, _git

REPOSITORY = "codearcheo-fixtures/offline-store"
PR_URL = f"https://github.com/{REPOSITORY}/pull/42"
FIXTURE = Path(__file__).with_name("fixtures") / "github_context.json"


def build_github_project(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
    (root / "README.md").write_text("# Offline store\nA tiny local store.\n")
    (root / "app.py").write_text(
        'import sqlite3\n\ndef connect():\n    return sqlite3.connect("store.db")\n'
    )
    _commit(root, "Use SQLite datastore", "2024-02-01T10:00:00+00:00")
    return root


class RecordedGitHubClient:
    """Replay public synthetic source responses; this never fakes the model's answer."""

    def get(self, endpoint: str):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        prefix = f"repos/{REPOSITORY}/"
        if not endpoint.startswith(prefix):
            raise github.GitHubError("Unrecorded GitHub repository in synthetic evaluation.")
        path = endpoint[len(prefix):]
        if path.startswith("commits/") and "/pulls?" in path:
            return data["pulls"]
        key = path.split("?", 1)[0]
        if key not in data:
            raise github.GitHubError("Unrecorded GitHub endpoint in synthetic evaluation.")
        return data[key]


@contextmanager
def replay_github():
    """Use only around this synthetic evaluation; real repository clients remain unchanged."""
    with patch("codearcheo.github.GitHubClient", RecordedGitHubClient):
        yield
