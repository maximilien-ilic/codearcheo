"""Parsed modules are cached by content hash: a second scan of a large project is cheap."""

import gzip

import pytest

from learn_it.analyzers import code

pytest.importorskip("tree_sitter")


class _NoMemory(dict):
    def __setitem__(self, key, value):  # every analyze goes through the disk cache
        pass


@pytest.fixture(autouse=True)
def disk_cache_only(request, monkeypatch):
    if "memory" not in request.node.name:
        monkeypatch.setattr(code, "_LAST_GRAPH", _NoMemory())


@pytest.fixture
def parses(monkeypatch):
    calls = []
    original = code._parse

    def counted(path, language, data):
        calls.append(path)
        return original(path, language, data)

    monkeypatch.setattr(code, "_parse", counted)
    return calls


def test_unchanged_files_are_not_parsed_twice(project, parses):
    first = code.analyze(project.root)
    parses.clear()

    second = code.analyze(project.root)

    assert parses == []
    assert second.modules.keys() == first.modules.keys()
    assert second.modules["app.py"].model_dump() == first.modules["app.py"].model_dump()


def test_an_edited_file_is_parsed_again_and_others_are_not(project, parses):
    (project.root / "worker.py").write_text("import app\n")
    code.analyze(project.root)
    parses.clear()
    (project.root / "app.py").write_text("from fastapi import FastAPI\n\ndef new(): pass\n")

    graph = code.analyze(project.root)

    assert parses == ["app.py"]
    assert "new" in {s.name for s in graph.modules["app.py"].symbols}


def test_a_corrupt_cache_is_ignored(project, parses):
    code.analyze(project.root)
    (project.root / ".learn-it" / "code-cache.json.gz").write_bytes(b"not gzip")
    parses.clear()

    graph = code.analyze(project.root)

    assert "app.py" in parses and "app.py" in graph.modules


def test_a_refused_file_is_not_parsed_again(project, parses, monkeypatch):
    """Generated tables over the node budget were reparsed on every scan of golang/go."""
    monkeypatch.setattr(code, "MAX_NODES", 5)
    first = code.analyze(project.root)
    assert "app.py" in first.skipped
    parses.clear()

    second = code.analyze(project.root)

    assert parses == []
    assert second.skipped["app.py"] == first.skipped["app.py"]


def test_cache_keeps_symbol_and_reference_paths_after_a_rename(project, parses):
    source = project.root / "worker.py"
    source.write_text("def greet(): return greeting\n")
    code.analyze(project.root)
    source.rename(project.root / "renamed.py")
    parses.clear()

    module = code.analyze(project.root).modules["renamed.py"]

    assert parses == []
    assert [symbol.path for symbol in module.symbols] == ["renamed.py"]
    assert [reference.path for reference in module.references] == ["renamed.py"]


def test_legacy_cache_is_migrated_without_reparsing_or_changing_the_graph(project, parses):
    first = code.analyze(project.root)
    compressed = project.root / ".learn-it/code-cache.json.gz"
    legacy = project.root / ".learn-it/code-cache.json"
    legacy.write_bytes(gzip.decompress(compressed.read_bytes()))
    compressed.unlink()
    parses.clear()

    second = code.analyze(project.root)

    assert parses == []
    assert second.model_dump() == first.model_dump()
    assert compressed.is_file()
    assert not legacy.exists()


def test_oversized_decompressed_cache_is_ignored(project, parses, monkeypatch):
    first = code.analyze(project.root)
    parses.clear()
    monkeypatch.setattr(code, "MAX_CACHE_BYTES", 10)

    second = code.analyze(project.root)

    assert "app.py" in parses
    assert second.model_dump() == first.model_dump()


def test_a_broken_cached_record_is_repaired_for_the_next_scan(project, parses):
    from learn_it.store import Store

    first = code.analyze(project.root)
    store = Store(project.root)
    cached = store.load_compressed_json("code-cache.json.gz", max_bytes=1_000_000)
    next(entry for entry in cached["modules"].values() if "language" in entry).pop("language")
    store.save_compressed_json("code-cache.json.gz", cached)

    assert code.analyze(project.root).model_dump() == first.model_dump()
    parses.clear()
    assert code.analyze(project.root).model_dump() == first.model_dump()
    assert parses == []


def test_a_failed_migration_keeps_the_legacy_cache(project, monkeypatch):
    from learn_it.store import Store

    first = code.analyze(project.root)
    compressed = project.root / ".learn-it/code-cache.json.gz"
    legacy = project.root / ".learn-it/code-cache.json"
    legacy.write_bytes(gzip.decompress(compressed.read_bytes()))
    original = legacy.read_bytes()
    compressed.unlink()

    def failed(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Store, "save_compressed_json", failed)

    assert code.analyze(project.root).model_dump() == first.model_dump()
    assert legacy.read_bytes() == original


def test_oversized_replacement_keeps_usable_legacy_cache(project, parses, monkeypatch):
    from learn_it.store import Store

    code.analyze(project.root)
    store = Store(project.root)
    compressed = store.dir / "code-cache.json.gz"
    legacy = store.dir / "code-cache.json"
    original = gzip.decompress(compressed.read_bytes())
    legacy.write_bytes(original)
    compressed.unlink()
    monkeypatch.setattr(code, "MAX_CACHE_BYTES", len(original))
    (project.root / "new.py").write_text("def extra():\n    return 42\n", encoding="utf-8")
    parses.clear()

    graph = code.analyze(project.root)

    assert "new.py" in graph.modules
    assert "new.py" in parses and "app.py" not in parses
    assert legacy.read_bytes() == original
    assert not compressed.exists()


def test_the_last_graph_is_kept_in_memory_until_a_source_changes(project, parses, tmp_path):
    first = code.analyze(project.root)
    parses.clear()
    assert code.analyze(project.root) is first
    assert code.analyze(project.root, None) is first

    (project.root / "app.py").write_text("from fastapi import FastAPI\n\ndef added(): pass\n")
    edited = code.analyze(project.root)
    assert edited is not first and parses == ["app.py"]
    assert "added" in {symbol.name for symbol in edited.modules["app.py"].symbols}

    (project.root / "extra.py").write_text("import app\n")
    assert "extra.py" in code.analyze(project.root).modules


def test_memory_is_kept_per_file_list(project):
    every = code.analyze(project.root)
    only = code.analyze(project.root, ["app.py"])
    assert only is not every and list(only.modules) == ["app.py"]


def test_memory_is_invalidated_when_the_go_module_changes(project):
    (project.root / "pkg").mkdir()
    (project.root / "pkg/lib.go").write_text("package pkg\n")
    (project.root / "main.go").write_text('package main\nimport "example.com/demo/pkg"\n')
    manifest = project.root / "go.mod"
    manifest.write_text("module example.com/demo\n")

    first = code.analyze(project.root)
    assert ("main.go", "pkg/lib.go") in first.edges()

    manifest.write_text("module example.com/renamed\n")
    assert ("main.go", "pkg/lib.go") not in code.analyze(project.root).edges()


def test_memory_is_invalidated_by_a_replacement_with_the_same_size_and_mtime(project):
    import os

    source = project.root / "worker.py"
    source.write_text("def old(): pass\n")
    before = source.stat()
    code.analyze(project.root)

    replacement = project.root / "replacement.py"
    replacement.write_text("def new(): pass\n")
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(source)

    module = code.analyze(project.root).modules["worker.py"]
    assert [symbol.name for symbol in module.symbols] == ["new"]


def test_overlapping_analyses_keep_gc_suspended_until_the_last_exit():
    import gc
    from contextlib import ExitStack

    with ExitStack() as first, ExitStack() as second:
        first.enter_context(code._without_gc())
        second.enter_context(code._without_gc())
        first.close()
        assert not gc.isenabled()
    assert gc.isenabled()
