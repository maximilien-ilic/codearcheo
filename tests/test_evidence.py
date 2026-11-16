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
