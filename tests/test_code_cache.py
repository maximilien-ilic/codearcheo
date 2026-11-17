"""Parsed modules are cached by content hash: a second scan of a large project is cheap."""

import pytest

from learn_it.analyzers import code

pytest.importorskip("tree_sitter")


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
    (project.root / ".learn-it" / "code-cache.json").write_text("{not json")
    parses.clear()

    graph = code.analyze(project.root)

    assert "app.py" in parses and "app.py" in graph.modules
