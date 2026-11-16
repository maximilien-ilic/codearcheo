from learn_it.analyzers import scan
from learn_it.sources import Project


def test_scan_finds_stack_adoption_history_and_work_in_progress(project):
    profile = scan(project)
    techs = {t.name: t for t in profile.technologies}

    assert techs["FastAPI"].category == "framework"
    assert techs["FastAPI"].adopted.subject == "Switch from Flask to FastAPI for async support"
    assert "Flask" not in techs  # removed since: no longer part of the stack
    assert techs["PostgreSQL"].source == "docker-compose.yml"
    assert techs["PostgreSQL"].adopted.subject == "Add Docker and CI"
    assert {"SQLAlchemy", "Docker", "Docker Compose", "GitHub Actions"} <= techs.keys()

    assert profile.languages == {"Python": 1}
    assert (profile.commits, profile.contributors) == (3, 1)
    assert {h.path for h in profile.hotspots if h.commits == 2} == {"app.py", "pyproject.toml"}
    assert profile.recent_commits[0].subject == "Add Docker and CI"
    assert "README.md" in profile.docs
    assert profile.uncommitted == ["notes.md"]  # the ignored .env does not show up


def test_scan_outside_git(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"next": "15.0.0"}, "devDependencies": {"left-pad": "1.3.0"}}'
    )
    profile = scan(Project(root=tmp_path, name="web"))

    assert {t.name: t.category for t in profile.technologies} == {
        "Next.js": "framework",
        "left-pad": "library",
    }
    assert profile.head is None and profile.commits == 0
