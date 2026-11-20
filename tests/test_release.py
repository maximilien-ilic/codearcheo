"""Release checks run against actual built archives, with deliberate packaging damage."""

import shutil
import subprocess
import tomllib
import zipfile

import pytest
import yaml

from scripts.check_dist import ROOT, check_dist


@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    directory = tmp_path_factory.mktemp("built-packages")
    subprocess.run(["uv", "build", "--no-sources", "--out-dir", str(directory)],
                   cwd=ROOT, check=True, capture_output=True)
    return directory


@pytest.fixture
def release_tree(tmp_path, packages):
    for name in ("pyproject.toml", "LICENSE"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    init = tmp_path / "src/codearcheo/__init__.py"
    init.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "src/codearcheo/__init__.py", init)
    version = tomllib.loads((tmp_path / "pyproject.toml").read_text())["project"]["version"]
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n## [{version}] - 2026-11-18\n")
    shutil.copytree(packages, tmp_path / "dist")
    return tmp_path, version


def test_both_built_packages_have_consistent_metadata_and_license(release_tree):
    root, version = release_tree
    assert len(check_dist(root, root / "dist", tag=f"v{version}")) == 2


def test_release_tag_must_match_the_packaged_version(release_tree):
    root, _ = release_tree
    with pytest.raises(ValueError, match="tag"):
        check_dist(root, root / "dist", tag="v99.0.0")


def test_source_version_must_match_package_metadata(release_tree):
    root, _ = release_tree
    (root / "src/codearcheo/__init__.py").write_text('__version__ = "99.0.0"\n')
    with pytest.raises(ValueError, match="versions"):
        check_dist(root, root / "dist")


def test_a_release_requires_dated_notes(release_tree):
    root, version = release_tree
    (root / "CHANGELOG.md").write_text("## [Unreleased]\n")
    with pytest.raises(ValueError, match="datée"):
        check_dist(root, root / "dist", tag=f"v{version}")
    assert check_dist(root, root / "dist")  # preparation remains possible before a release


def test_stale_distributions_cannot_be_uploaded_together(release_tree):
    root, _ = release_tree
    wheel, = (root / "dist").glob("*.whl")
    shutil.copyfile(wheel, root / "dist/stale.whl")
    with pytest.raises(ValueError, match="exactement"):
        check_dist(root, root / "dist")


def test_an_artifact_filename_cannot_prefix_a_different_version(release_tree):
    root, version = release_tree
    wheel, = (root / "dist").glob("*.whl")
    wheel.rename(wheel.with_name(wheel.name.replace(version, version + "1", 1)))
    with pytest.raises(ValueError, match="Nom d'archive"):
        check_dist(root, root / "dist")


def test_missing_wheel_license_is_detected(release_tree):
    root, _ = release_tree
    wheel, = (root / "dist").glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()
                   if not info.filename.endswith("/LICENSE")]
    with zipfile.ZipFile(wheel, "w") as archive:
        for info, data in entries:
            archive.writestr(info, data)
    with pytest.raises(ValueError, match="Licence"):
        check_dist(root, root / "dist")


def test_publish_credentials_are_not_available_to_build_or_manual_preparation():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert set(workflow["on"]) == {"workflow_dispatch", "release"}
    assert workflow["permissions"] == {"contents": "read"}
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "verify-artifacts"
    assert workflow["jobs"]["verify-artifacts"]["needs"] == "build"
    assert "permissions" not in workflow["jobs"]["verify-artifacts"]
    assert "github.event_name == 'release'" in publish["if"]
    assert "!github.event.release.prerelease" in publish["if"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["permissions"] == {"id-token": "write"}
    assert not any("checkout" in step.get("uses", "") for step in publish["steps"])
