import pytest

from learn_it.domain import Decision
from learn_it.export import export_decisions


@pytest.fixture
def decision():
    return Decision(
        title="Une base PostgreSQL", category="data", context="Conserver les commandes.",
        decision="Utiliser PostgreSQL.", rationale="Le commit le dit.",
        rationale_source="documented", consequences=["Schéma relationnel."],
        evidence=["`database.py:1`"],
    )


def test_export_continues_existing_numbering_and_does_not_overwrite(tmp_path, decision):
    directory = tmp_path / "docs/adr"
    directory.mkdir(parents=True)
    existing = directory / "0007-architecture.md"
    existing.write_text("untouched")
    exported = export_decisions(tmp_path, [decision], directory)
    assert exported[0].name == "0008-une-base-postgresql.md"
    text = exported[0].read_text()
    assert "Reconstituée par learn-it" in text
    assert "justification documentée" in text
    assert "`database.py:1`" in text
    assert existing.read_text() == "untouched"
    with pytest.raises(FileExistsError):
        export_decisions(tmp_path, [decision], directory)
    changed = decision.model_copy(update={"rationale": "Nouvelle explication."})
    assert export_decisions(tmp_path, [changed], directory, force=True) == exported
    assert "Nouvelle explication" in exported[0].read_text()


def test_export_checks_whole_batch_before_writing(tmp_path, decision):
    other = decision.model_copy(update={"title": "Different"})
    export_decisions(tmp_path, [decision], tmp_path)
    with pytest.raises(FileExistsError):
        export_decisions(tmp_path, [other, decision], tmp_path)
    assert not list(tmp_path.glob("*different*"))


def test_export_refuses_links_and_escape_even_with_force(tmp_path, decision):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        export_decisions(root, [decision], root / "linked", force=True)
    with pytest.raises(ValueError):
        export_decisions(root, [decision], outside)
    target = root / "0001-une-base-postgresql.md"
    private = outside / "private.md"
    private.write_text("unchanged")
    target.symlink_to(private)
    with pytest.raises(OSError):
        export_decisions(root, [decision], root, force=True)
    assert private.read_text() == "unchanged"
