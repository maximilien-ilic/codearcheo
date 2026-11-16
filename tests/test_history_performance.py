from pathlib import Path

from evals.shop import _commit, _git
from learn_it import git
from learn_it.analyzers import history, scan
from learn_it.domain import Technology


def test_batch_adoption_matches_pickaxe_after_removal_readdition_and_rename(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    manifest = root / "package.json"
    for content, subject, date in [
        ('{"dependencies":{"react":"1","vue":"1"}}\n', "initial", "2020-01-01"),
        ('{"dependencies":{"vue":"1"}}\n', "remove react", "2020-02-01"),
        ('{"dependencies":{"react":"2","vue":"2"}}\n', "restore react", "2020-03-01"),
    ]:
        manifest.write_text(content)
        _commit(root, subject, date + "T00:00:00Z")
    group = [Technology(name=name, category="ui", source="package.json", needle=needle)
             for name, needle in [("React", '"react"'), ("Vue", '"vue"'),
                                  ("file", None), ("missing", "NOT_PRESENT")]]
    history.date_technologies(root, group)
    for tech in group:
        assert tech.adopted == history.first_commit(root, tech.source, tech.needle)

    _git(root, "mv", "package.json", "renamed.json")
    _commit(root, "rename", "2020-04-01T00:00:00Z")
    for tech in group:
        tech.source = "renamed.json"
    history.date_technologies(root, group)
    for tech in group:
        assert tech.adopted == history.first_commit(root, tech.source, tech.needle)


def test_more_dependencies_do_not_add_git_history_walks(project, monkeypatch):
    manifest = project.root / "package.json"
    manifest.write_text('{"dependencies":{"react":"1","vue":"1","next":"1",'
                        '"typescript":"1","svelte":"1","express":"1"}}')
    calls = []
    original = git.run

    def record(root: Path, *args, **kwargs):
        calls.append(args)
        return original(root, *args, **kwargs)

    monkeypatch.setattr(git, "run", record)
    profile = scan(project)
    walks = [args for args in calls if args[0] == "log" and "-p" in args]
    assert len(walks) == len({tech.source for tech in profile.technologies
                              if tech.category != "library"})
    assert len([args for args in walks if args[-1] == "package.json"]) == 1
    assert not any(any(str(arg).startswith("-S") for arg in args) for args in calls)
    # GitHub origin detection adds one bounded lookup, never a history traversal.
    assert len(calls) <= 13


def test_activity_matches_reference_with_mailmap_and_multiple_roots(project):
    (project.root / ".mailmap").write_text("Ada Lovelace <ada@example.com> Ada <ada@example.com>\n")
    identity = ("-c", "user.name=Ada", "-c", "user.email=ada@example.com",
                "-c", "commit.gpgsign=false")
    tree = git.run(project.root, "rev-parse", "HEAD^{tree}").strip()
    other = git.run(project.root, *identity, "commit-tree", tree, "-m", "unrelated root").strip()
    merged = git.run(project.root, *identity, "commit-tree", tree, "-p", "HEAD", "-p", other,
                     "-m", "merge both roots").strip()
    git.run(project.root, "update-ref", "HEAD", merged)
    expected_count = int(git.run(project.root, "rev-list", "--count", "HEAD"))
    expected_people = len(git.run(project.root, "shortlog", "-sn", "HEAD").splitlines())
    count, people, first = history.activity(project.root)
    assert (count, people) == (expected_count, expected_people)
    assert first.isoformat() == "2023-01-10T10:00:00+00:00"


def test_empty_repository_has_no_activity(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    assert history.activity(tmp_path) == (0, 0, None)


def test_forced_text_patch_control_characters_cannot_forge_history_records(project):
    (project.root / ".gitattributes").write_text("*.yml diff\n")
    workflow = ".github/workflows/ci.yml"
    (project.root / workflow).write_bytes(b"on: push\n\0FORGED_HEADER\x1enew file mode 100644\n")
    _commit(project.root, "force binary data as text", "2024-03-01T00:00:00Z")
    tech = Technology(name="GitHub Actions", category="ci", source=workflow)
    history.date_technologies(project.root, [tech])
    assert tech.adopted == history.first_commit(project.root, workflow)


def test_batch_adoption_is_independent_of_color_configuration(project):
    git.run(project.root, "config", "color.ui", "always")
    tech = Technology(name="FastAPI", category="framework", source="pyproject.toml",
                      needle="fastapi")
    history.date_technologies(project.root, [tech])
    assert tech.adopted == history.first_commit(project.root, tech.source, tech.needle)
