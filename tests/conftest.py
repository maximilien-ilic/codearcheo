import os
import subprocess
from pathlib import Path

import pytest

from learn_it.sources import Project

# Isolated from the user's git config: no signing, no hooks, a fixed identity.
GIT = ["git", "-c", "user.name=Ada", "-c", "user.email=ada@example.com",
       "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def commit(root: Path, message: str, date: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run([*GIT, "-C", str(root), "add", "-A"], check=True, env=env)
    subprocess.run([*GIT, "-C", str(root), "commit", "-q", "-m", message], check=True, env=env)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """A small API that moved from Flask to FastAPI, then got Docker and CI, with work in
    progress and an ignored secret."""
    root = tmp_path / "shop"
    root.mkdir()
    subprocess.run([*GIT, "init", "-q", "-b", "main", str(root)], check=True)

    (root / "README.md").write_text("# Shop\nA tiny shop API.\n")
    (root / ".gitignore").write_text(".env\n")
    (root / "pyproject.toml").write_text('[project]\nname = "shop"\ndependencies = ["flask>=2"]\n')
    (root / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
    commit(root, "Initial Flask app", "2023-01-10T10:00:00+00:00")

    (root / "pyproject.toml").write_text(
        '[project]\nname = "shop"\ndependencies = ["fastapi>=0.100", "sqlalchemy>=2"]\n'
    )
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\napp = FastAPI()  # async endpoints for the checkout\n"
    )
    commit(root, "Switch from Flask to FastAPI for async support", "2023-06-01T10:00:00+00:00")

    (root / "Dockerfile").write_text("FROM python:3.12-slim\n")
    (root / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:16\n")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text("on: push\n")
    commit(root, "Add Docker and CI", "2024-02-01T10:00:00+00:00")

    (root / "notes.md").write_text("TODO: payments\n")  # untracked work in progress
    (root / ".env").write_text("STRIPE_KEY=sk_live_secret\n")  # ignored secret
    return Project(root=root, name="shop")
