"""The project inventory: what may be listed, read and cited."""

from fnmatch import fnmatch

import pytest

from codearcheo.analyzers import inventory


@pytest.mark.parametrize("git_repo", [True, False])
def test_listing_skips_symlinks_secrets_and_symlinked_folders(project, tmp_path, git_repo):
    root = project.root
    if not git_repo:
        root = tmp_path / "plain"
        root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.py").write_text("token = 1\n")
    (root / "pkg" / "deep").mkdir(parents=True)
    (root / "pkg" / "deep" / "module.py").write_text("x = 1\n")
    (root / "pkg" / "deep" / ".env.local").write_text("KEY=1\n")
    (root / "pkg" / "deep" / ".env.example").write_text("KEY=\n")
    (root / "pkg" / "linked").symlink_to(outside, target_is_directory=True)
    (root / "pkg" / "alias.py").symlink_to(root / "pkg" / "deep" / "module.py")

    files = inventory.list_files(root)

    assert "pkg/deep/module.py" in files
    assert "pkg/deep/.env.example" in files
    assert not {"pkg/deep/.env.local", "pkg/linked/private.py", "pkg/alias.py"} & set(files)
    assert files == sorted(files)


@pytest.mark.parametrize(("path", "secret"), [
    ("a/.env", True), ("a/.env.prod", True), ("a/.env.example", False), ("k/server.key", True),
    ("id_rsa.pub", True), ("keys/notes.md", False), ("a.KEY", fnmatch("a.KEY", "*.key")),
    (".npmrc", True),
])
def test_secret_names(path, secret):
    assert inventory.is_secret(path) is secret


def test_code_analysis_restores_the_garbage_collector(project):
    import gc

    from codearcheo.analyzers import code

    code.analyze(project.root)
    assert gc.isenabled()
    gc.disable()
    try:
        code.analyze(project.root)
        assert not gc.isenabled()  # a caller's choice is kept
    finally:
        gc.enable()


def test_secret_names_follow_filesystem_case_rules(monkeypatch):
    import ntpath

    monkeypatch.setattr(inventory, "normcase", ntpath.normcase)

    assert inventory.is_secret("config/SERVER.KEY")
    assert inventory.is_secret("config/.ENV")
    assert not inventory.is_secret("config/.env.example")


def test_listing_can_skip_a_deep_missing_tracked_file(tmp_path):
    path = "/".join(["a"] * 1100 + ["source.py"])

    assert inventory.safe_files(tmp_path, [path]) == []
