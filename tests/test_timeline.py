import pytest

from learn_it import git
from learn_it.analyzers import scan
from learn_it.store import Store
from learn_it.timeline import compare


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
    clean = dirty.model_copy(update={"uncommitted": []})
    store.save_profile(clean)
    changed = clean.model_copy(update={"files": 10000})
    store.save_profile(changed)
    assert store.history_profile(clean.head).files == clean.files
    assert store.load_profile().files == 10000


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
