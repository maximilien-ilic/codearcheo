import gzip

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


def test_compressed_json_roundtrips_with_a_decompressed_byte_limit(tmp_path):
    store = Store(tmp_path)
    data = {"é": "a" * 10000}
    path = store.save_compressed_json("cache.json.gz", data)

    assert path.stat().st_size < 1000
    assert store.load_compressed_json("cache.json.gz", max_bytes=20000) == data
    assert store.load_compressed_json("cache.json.gz", max_bytes=100) is None


@pytest.mark.parametrize("payload", [b"not gzip", gzip.compress(b"{broken"),
                                    gzip.compress(b'{"valid":true}')[:-5]])
def test_bad_compressed_json_is_a_cache_miss(tmp_path, payload):
    store = Store(tmp_path)
    store.dir.mkdir()
    (store.dir / "cache.json.gz").write_bytes(payload)
    assert store.load_compressed_json("cache.json.gz", max_bytes=1000) is None


def test_compressed_cache_refuses_linked_files_for_reads_writes_and_removal(tmp_path):
    store = Store(tmp_path)
    store.dir.mkdir()
    private = tmp_path / "private.gz"
    original = gzip.compress(b'{"secret":true}')
    private.write_bytes(original)
    (store.dir / "cache.json.gz").symlink_to(private)

    with pytest.raises(OSError):
        store.load_compressed_json("cache.json.gz", max_bytes=1000)
    with pytest.raises(OSError):
        store.save_compressed_json("cache.json.gz", {})
    with pytest.raises(OSError):
        store.remove("cache.json.gz")
    assert private.read_bytes() == original


def test_legacy_json_reads_can_be_bounded_too(tmp_path):
    store = Store(tmp_path)
    store.save_json("cache.json", {"data": "x" * 100})
    assert store.load_json("cache.json", max_bytes=10) is None
    assert store.load_json("cache.json", max_bytes=1000) == {"data": "x" * 100}


def test_failed_compressed_cache_publish_keeps_previous_cache(tmp_path, monkeypatch):
    store = Store(tmp_path)
    path = store.save_compressed_json("cache.json.gz", {"previous": True})
    original = path.read_bytes()

    def fail_replace(self, target):
        raise OSError("replacement failed")

    monkeypatch.setattr(type(path), "replace", fail_replace)

    with pytest.raises(OSError, match="replacement failed"):
        store.save_compressed_json("cache.json.gz", {"previous": False})
    assert path.read_bytes() == original
    assert {item.name for item in store.dir.iterdir()} == {".gitignore", path.name}
