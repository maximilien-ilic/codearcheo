import pytest

from evals.scoring import commits_with_subject
from learn_it.evidence import find_citations, mentioned_paths, verify


def test_finds_line_ranges_and_commits():
    text = (
        "Voir `app.py:3`, `./src/db.py:10-20` et `x.py:1–2`, "
        "puis le commit `abc1234` et commit DEF5678."
    )
    citations = find_citations(text)

    assert [(c.path, c.start, c.end) for c in citations if c.path] == [
        ("app.py", 3, 3), ("src/db.py", 10, 20), ("x.py", 1, 2),
    ]
    assert [c.sha for c in citations if c.sha] == ["abc1234", "def5678"]
    assert mentioned_paths("`app.py` et `Dockerfile:1`") == {"app.py", "Dockerfile"}


def test_real_citations_check_out(project):
    switch = commits_with_subject(project.root, "Switch from Flask")[0]

    report = verify(f"`app.py:1-3`, `Dockerfile:1` et commit {switch[:7]}.", project.root)

    assert report.ok, report.problems


@pytest.mark.parametrize(
    "citation, problem",
    [
        ("`app.py:4`", "lignes hors du fichier"),
        ("`app.py:3-1`", "lignes hors du fichier"),
        ("`app.py:0`", "lignes hors du fichier"),
        ("`missing.py:1`", "fichier introuvable"),
        ("`.env:1`", "fichier introuvable"),  # a secret is never valid evidence
        ("`../outside.py:1`", "fichier introuvable"),
        ("commit 0123abc", "commit introuvable"),
    ],
)
def test_invented_citations_are_caught(project, citation, problem):
    report = verify(f"Selon {citation}.", project.root)

    assert not report.ok
    assert list(report.problems.values())[0].startswith(problem)


def test_an_answer_without_citations_is_not_evidenced(project):
    assert not verify("FastAPI remplace Flask, sans source.", project.root).ok


def test_plain_citations_are_checked_without_treating_time_as_a_file(project):
    report = verify("À 12:30, lire app.py:1 et lost.py:12.", project.root)
    assert len(report.citations) == 2
    assert len(report.problems) == 1
    assert next(iter(report.problems)).path == "lost.py"


def test_hidden_and_ignored_files_are_not_valid_evidence(project):
    (project.root / "credentials.json").write_text("{}")
    (project.root / ".gitignore").write_text(".env\ncredentials.json\n")
    report = verify("app.py:1 and .env:1 and `credentials.json:1`", project.root)
    assert len(report.citations) == 3
    assert len(report.problems) == 2


def test_unknown_standalone_extensions_require_an_explicit_project_path(project):
    (project.root / "schema.custom").write_text("field = 1\n")
    report = verify("`schema.custom:1` et `./schema.custom:1`", project.root)
    assert report.ok
    assert [citation.ref for citation in report.citations] == ["`./schema.custom:1`"]


def test_unique_bare_file_names_are_completed_and_ambiguous_ones_left(project):
    from learn_it.analyzers import inventory
    from learn_it.evidence import complete_paths

    (project.root / "pkg").mkdir()
    (project.root / "pkg" / "app.py").write_text("x = 1\n")  # now two app.py
    files = inventory.list_files(project.root)

    assert complete_paths("- ci.yml:1 et Dockerfile:1", files) == (
        "- .github/workflows/ci.yml:1 et Dockerfile:1"
    )
    assert complete_paths("app.py:1", files) == "app.py:1"  # ambiguous: not guessed
    assert complete_paths("`.github/workflows/ci.yml:1`", files) == "`.github/workflows/ci.yml:1`"


def test_an_ambiguous_name_is_completed_from_a_path_the_text_cites_in_full(project):
    from learn_it.analyzers import inventory
    from learn_it.evidence import complete_paths

    for folder in ("pkg", "other"):
        (project.root / folder).mkdir()
        (project.root / folder / "helper.py").write_text("x = 1\n")
    files = inventory.list_files(project.root)
    text = "Voir pkg/helper.py:1. Plus loin : helper.py:1."

    assert complete_paths(text, files) == "Voir pkg/helper.py:1. Plus loin : pkg/helper.py:1."


@pytest.mark.parametrize("reference", ["app.py:1", "`app.py:1`", "./app.py:1"])
def test_a_root_path_is_never_redirected_to_a_different_file(reference):
    from learn_it.evidence import complete_paths

    text = f"Voir pkg/app.py:1. Puis {reference}."
    assert complete_paths(text, ["app.py", "pkg/app.py"]) == text


def test_an_explicit_relative_path_is_not_relocated():
    from learn_it.evidence import complete_paths

    text = "Voir `./helper.py:1` et ./helper.py:1."
    assert complete_paths(text, ["pkg/helper.py"]) == text


def test_fenced_examples_cannot_disambiguate_a_citation():
    from learn_it.evidence import complete_paths

    text = "```text\n`pkg/helper.py`\n```\nVoir helper.py:1."
    assert complete_paths(text, ["pkg/helper.py", "other/helper.py"]) == text


def test_path_completion_does_not_make_invalid_line_ranges_pass(project):
    from learn_it.evidence import complete_paths

    text = complete_paths("ci.yml:999", [".github/workflows/ci.yml"])
    assert text == ".github/workflows/ci.yml:999"
    assert not verify(text, project.root).ok


def test_completed_path_with_spaces_still_verifies(project):
    from learn_it.analyzers import inventory
    from learn_it.evidence import complete_paths

    folder = project.root / "docs/getting started"
    folder.mkdir(parents=True)
    (folder / "guide.md").write_text("Start here.\n", encoding="utf-8")
    text = complete_paths("Voir guide.md:1.", inventory.list_files(project.root))

    assert text == "Voir `docs/getting started/guide.md:1`."
    report = verify(text, project.root)
    assert report.ok
    assert [citation.path for citation in report.citations] == ["docs/getting started/guide.md"]
