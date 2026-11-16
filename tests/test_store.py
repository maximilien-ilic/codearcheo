import pytest

from learn_it.store import Store


def test_store_refuses_a_linked_output_directory(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ".learn-it").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        Store(root).save_report("review", "must stay in the project")
    assert not list(outside.iterdir())


def test_store_refuses_a_linked_output_file(tmp_path):
    output = tmp_path / ".learn-it"
    output.mkdir()
    private = tmp_path / "private.txt"
    private.write_text("unchanged")
    (output / "review.md").symlink_to(private)

    with pytest.raises(OSError):
        Store(tmp_path).save_report("review", "overwrite")
    assert private.read_text() == "unchanged"


def test_existing_store_is_self_ignored(tmp_path):
    (tmp_path / ".learn-it").mkdir()
    store = Store(tmp_path)
    store.save_report("review", "report")

    assert (store.dir / ".gitignore").read_text().splitlines()[-1] == "*"
    assert (store.dir / "review.md").read_text() == "report"


@pytest.mark.parametrize("name,load", [("profile.json", "load_profile"),
                                       ("decisions.json", "load_decisions")])
def test_store_refuses_linked_input_files(tmp_path, name, load):
    output = tmp_path / ".learn-it"
    output.mkdir()
    private = tmp_path / "private.json"
    private.write_text("{}")
    (output / name).symlink_to(private)

    with pytest.raises(OSError):
        getattr(Store(tmp_path), load)()


@pytest.mark.parametrize("name", ["../outside", "absolute", "nested/report"])
def test_report_names_cannot_escape_the_store(tmp_path, name):
    if name == "absolute":
        name = str(tmp_path / "outside")
    with pytest.raises(ValueError):
        Store(tmp_path).save_report(name, "report")
