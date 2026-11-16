import pytest

from learn_it.sources import parse_github, resolve


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/fastapi/fastapi",
        "https://github.com/fastapi/fastapi.git",
        "git@github.com:fastapi/fastapi.git",
        "github.com/fastapi/fastapi",
        "https://github.com/fastapi/fastapi/tree/master/docs",
    ],
)
def test_parse_github_accepts_the_usual_forms(url):
    assert parse_github(url) == ("fastapi", "fastapi")


@pytest.mark.parametrize("path", [".", "./src", "/home/me/github.com/x"])
def test_local_paths_are_not_github(path):
    assert parse_github(path) is None


def test_resolve_local_directory(project, tmp_path):
    resolved = resolve(str(project.root), tmp_path / "cache")
    assert resolved.root == project.root.resolve()
    assert resolved.name == "shop"
    assert resolved.origin is None


def test_resolve_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve(str(tmp_path / "missing"), tmp_path / "cache")
