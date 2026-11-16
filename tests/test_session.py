"""Issue #3: every command must see the project as it is now, committed or not."""

import pytest

from learn_it.cli import _session


@pytest.fixture(params=["git", "no-git"])
def root(request, project, tmp_path):
    if request.param == "git":
        return project.root
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "app.py").write_text("x = 1\n")
    (plain / "pyproject.toml").write_text('[project]\nname = "plain"\ndependencies = []\n')
    return plain


def profile(root):
    return _session(str(root)).profile


def add_redis(manifest):
    text = manifest.read_text()
    manifest.write_text(text.replace("dependencies = [", 'dependencies = ["redis", '))


def test_added_and_deleted_files_are_seen_without_a_commit(root):
    files = profile(root).files

    (root / "new.py").write_text("y = 2\n")
    assert profile(root).files == files + 1

    (root / "app.py").unlink()
    assert profile(root).files == files


def test_an_edited_manifest_is_seen_without_a_commit(root):
    assert "Redis" not in {t.name for t in profile(root).technologies}

    add_redis(root / "pyproject.toml")

    assert "Redis" in {t.name for t in profile(root).technologies}


def test_a_file_already_modified_is_seen_when_it_changes_again(root):
    """`git status` prints the same line both times: its text alone cannot detect this."""
    manifest = root / "pyproject.toml"
    manifest.write_text(manifest.read_text() + "# work in progress\n")
    assert "Redis" not in {t.name for t in profile(root).technologies}

    add_redis(manifest)

    assert "Redis" in {t.name for t in profile(root).technologies}
