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


@pytest.mark.parametrize("owner,repo", [("..", ".."), ("owner", "."), ("owner", ".."),
                                        ("owner", "--bare"), ("-owner", "repo")])
def test_invalid_github_names_do_not_reach_git(tmp_path, monkeypatch, owner, repo):
    from learn_it import git

    calls = []
    monkeypatch.setattr(git, "run", lambda *args, **kwargs: calls.append(args) or "")
    url = f"https://github.com/{owner}/{repo}"

    assert parse_github(url) is None
    with pytest.raises(ValueError, match="URL GitHub invalide"):
        resolve(url, tmp_path / "cache")
    assert calls == []
    assert not (tmp_path / "cache").exists()


def test_resolve_does_not_follow_a_linked_cache(tmp_path, monkeypatch):
    from learn_it import git

    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (cache / "repos").symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr(git, "run", lambda *args, **kwargs: calls.append(args) or "")

    with pytest.raises(OSError, match="lien symbolique"):
        resolve("https://github.com/owner/repo", cache)
    assert calls == []
    assert not list(outside.iterdir())
