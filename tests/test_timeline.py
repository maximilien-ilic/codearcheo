import pytest

from codearcheo import git
from codearcheo.analyzers import scan
from codearcheo.store import Store
from codearcheo.timeline import compare


def test_diff_reads_historical_techs_without_changing_checkout(project):
    root = project.root
    first = git.run(root, "rev-list", "--max-parents=0", "HEAD").strip()
    before_head = git.head(root)
    before_status = git.run(root, "status", "--porcelain")
    result = compare(project, Store(root), first)
    assert "FastAPI" in result.technologies_added
    assert "Flask" in result.technologies_removed
    assert result.before == first
    assert not result.decisions_available
    assert git.head(root) == before_head
    assert git.run(root, "status", "--porcelain") == before_status


def test_snapshots_are_immutable_and_dirty_work_is_not_labelled_as_committed(project):
    store = Store(project.root)
    dirty = scan(project)
    store.save_profile(dirty)
    assert store.history_profile(dirty.head) is None
    (project.root / "notes.md").unlink()
    clean = scan(project)
    store.save_profile(clean)
    changed = clean.model_copy(update={"files": 10000})
    store.save_profile(changed)
    assert store.history_profile(clean.head).files == clean.files
    assert store.load_profile().files == 10000


def test_corrupt_historical_json_is_unavailable_instead_of_breaking_diff(project):
    store = Store(project.root)
    sha = git.head(project.root)
    store.save_report("setup", "")
    folder = store.dir / "history" / sha
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text("{")
    (folder / "decisions.json").write_text("{")
    assert store.history_profile(sha) is None
    assert store.history_decisions(sha) is None
    assert compare(project, store, sha).before == sha


def test_historical_subdirectory_links_are_not_followed(tmp_path):
    from codearcheo.sources import Project
    from codearcheo.timeline import profile_at
    from evals.shop import _commit, _git

    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "pyproject.toml").write_text('[project]\ndependencies=["PRIVATE_CANARY"]\n')
    _git(root, "init", "-q", "-b", "main")
    (root / "app").symlink_to(outside, target_is_directory=True)
    _commit(root, "old link", "2020-01-01T00:00:00Z")
    sha = git.head(root)
    (root / "app").unlink()
    (root / "app").mkdir()
    (root / "app/README.md").write_text("Public\n")
    _commit(root, "normal folder", "2020-02-01T00:00:00Z")
    with pytest.raises(OSError):
        profile_at(Project(root / "app", "app"), sha)


def test_historical_checkout_does_not_execute_global_filters(project, tmp_path, monkeypatch):
    from codearcheo.timeline import profile_at
    from evals.shop import _commit

    marker = tmp_path / "FILTER_EXECUTED"
    config = tmp_path / "gitconfig"
    config.write_text(f'[filter "canary"]\n  smudge = touch {marker}; cat\n')
    (project.root / ".gitattributes").write_text("app.py filter=canary\n")
    _commit(project.root, "attributes", "2024-03-01T00:00:00Z")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    profile_at(project, git.head(project.root))
    assert not marker.exists()


def test_decision_diff_distinguishes_add_remove_change_and_missing_analysis(project):
    from codearcheo.domain import Decision
    from codearcheo.timeline import compare_profiles

    profile = scan(project)
    initial = Decision(
        title="Database", category="data", context="Need persistence", decision="SQLite",
        rationale="Local store", rationale_source="inferred", consequences=["Single file"],
        evidence=["`app.py:1`"],
    )
    removed = initial.model_copy(update={"title": "Removed"})
    added = initial.model_copy(update={"title": "Added"})
    changed = initial.model_copy(update={"decision": "PostgreSQL"})
    result = compare_profiles(profile, profile, [initial, removed], [changed, added])
    assert result.decisions_available
    assert result.decisions_added == ["Added"]
    assert result.decisions_removed == ["Removed"]
    assert result.decisions_changed == ["Database"]
    missing = compare_profiles(profile, profile, [initial], None)
    assert not missing.decisions_available
    assert not missing.decisions_removed


def test_snapshot_refuses_linked_history_and_revision_paths(project, tmp_path):
    store = Store(project.root)
    store.save_report("setup", "")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.dir / "history").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        store.history_profile("a" * 40)
    with pytest.raises(ValueError):
        store.history_profile("../../private")
    assert not list(outside.iterdir())


def test_an_example_only_technology_is_not_a_stack_change():
    from codearcheo.domain import ProjectProfile, Technology
    from codearcheo.timeline import compare_profiles

    def profile(*technologies):
        return ProjectProfile(name="p", files=1, languages={}, docs=[],
                              technologies=list(technologies))

    redis = Technology(name="Redis", category="data", source="examples/x/req.txt",
                       auxiliary=True)
    django = Technology(name="Django", category="framework", source="pyproject.toml")

    changes = compare_profiles(profile(), profile(redis, django))

    assert changes.technologies_added == ["Django"]


def test_legacy_snapshot_does_not_report_an_auxiliary_technology_as_removed():
    from codearcheo.domain import ProjectProfile
    from codearcheo.timeline import compare_profiles

    fields = {"name": "p", "files": 1, "languages": {}, "docs": []}
    redis = {"name": "Redis", "category": "data", "source": "Examples/demo/requirements.txt"}
    before = ProjectProfile.model_validate({**fields, "technologies": [redis]})
    after = ProjectProfile.model_validate({
        **fields, "technologies": [{**redis, "auxiliary": True}],
    })

    assert compare_profiles(before, after).technologies_removed == []
