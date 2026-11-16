from pathlib import Path

import pytest

from evals.shop import build_shop
from learn_it.sources import Project


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """The `shop` reference project (evals/shop.py): Flask then FastAPI, Docker and CI, with
    work in progress and an ignored secret."""
    return Project(root=build_shop(tmp_path / "shop"), name="shop")
