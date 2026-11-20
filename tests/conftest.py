import os
from pathlib import Path

import pytest

from codearcheo.sources import Project
from evals.shop import build_shop


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """The `shop` reference project (evals/shop.py): Flask then FastAPI, Docker and CI, with
    work in progress and an ignored secret."""
    return Project(root=build_shop(tmp_path / "shop"), name="shop")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """The developer's own settings (`CODEARCHEO_BACKEND`, or `LEARN_IT_*` from before the
    rename) must not change what a test exercises."""
    for name in list(os.environ):
        if name.startswith(("CODEARCHEO_", "LEARN_IT_")):
            monkeypatch.delenv(name)
