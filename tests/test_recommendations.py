import json
from dataclasses import replace
from pathlib import Path

import pytest
from anthropic.lib.tools import ToolError
from markdown_it import MarkdownIt
from typer.testing import CliRunner

from codearcheo import cli, features, recommendations
from codearcheo.analyzers import scan
from codearcheo.config import Settings
from codearcheo.domain import Recommendation
from codearcheo.features import Session
from codearcheo.store import Store


def recommendation(**updates):
    values = dict(
        title="Simplifier la configuration", decision="Configuration globale",
        verdict="improve", reasons=["Deux paramètres contradictoires."], proposal="Unifier.",
        effort="S", impact="high", first_steps=["Ajouter un test."], evidence=["`app.py:1`"],
    )
    return Recommendation(**(values | updates))


@pytest.fixture
def publication(project, monkeypatch):
    bodies = []

    def fake(*args):
        if args[1] == "list":
            return "[]"
        assert args[1] == "create"
        bodies.append(Path(args[args.index("--body-file") + 1]).read_text())
        return f"https://github.com/owner/repo/issues/{len(bodies)}"

    monkeypatch.setattr(recommendations, "_gh", fake)
    return replace(project, origin="https://github.com/owner/repo"), bodies


@pytest.mark.parametrize("field", [
    "title", "decision", "reasons", "proposal", "tradeoffs", "first_steps", "evidence",
])
def test_published_issue_keeps_invalid_citation_warnings(publication, field):
    project, bodies = publication
    value = "Voir `missing.py:9`."
    if field in {"reasons", "tradeoffs", "first_steps", "evidence"}:
        value = [value]

    recommendations.publish(project, [recommendation(**{field: value})], confirmed=True)

    warning = bodies[0].split("### Preuves non vérifiées\n", 1)[1]
    assert "missing.py:9" in warning
    assert "fichier introuvable" in warning


def test_publication_checks_evidence_again_after_the_review(publication):
    project, bodies = publication
    item = recommendation()
    assert "Preuves non vérifiées" not in recommendations.item_markdown(item)
    (project.root / "app.py").unlink()

    recommendations.publish(project, [item], confirmed=True)

    assert "### Preuves non vérifiées" in bodies[0]
    assert "fichier introuvable" in bodies[0]


@pytest.mark.parametrize("reference", ["`app.py:99999`", "commit deadbee", "source inconnue"])
def test_publication_flags_other_unverifiable_evidence(publication, reference):
    project, bodies = publication
    recommendations.publish(project, [recommendation(evidence=[reference])], confirmed=True)

    assert "### Preuves non vérifiées" in bodies[0]


@pytest.mark.parametrize("opening", ["```python", "~~~python", "> ```python", "- ```python"])
def test_open_example_cannot_hide_the_next_field_or_warning(publication, opening):
    project, bodies = publication
    prefix = "> " if opening.startswith(">") else "  " if opening.startswith("-") else ""
    item = recommendation(
        reasons=[f"{opening}\n{prefix}example.py:999"], proposal="Voir `missing.py:9`.",
    )

    recommendations.publish(project, [item], confirmed=True)

    body = bodies[0]
    warning_start = body.index("### Preuves non vérifiées")
    assert "<h3>Preuves non vérifiées</h3>" in MarkdownIt().render(body)
    assert "missing.py:9" in body[warning_start:]
    assert "example.py:999" not in body[warning_start:]


@pytest.mark.parametrize("field", ["reasons", "tradeoffs", "first_steps"])
@pytest.mark.parametrize("opening", ["```python", "~~~python"])
def test_multiline_list_item_preserves_the_next_item_and_warning(publication, field, opening):
    project, bodies = publication
    item = recommendation(**{field: [f"{opening}\nexample.py:999", "Voir missing.py:9."]})

    recommendations.publish(project, [item], confirmed=True)

    rendered = MarkdownIt().render(bodies[0])
    warning = rendered.split("<h3>Preuves non vérifiées</h3>", 1)[1]
    assert "missing.py:9" in warning
    assert "example.py:999" not in warning


def test_unrecognized_evidence_cannot_turn_the_warning_into_code(publication):
    project, bodies = publication
    item = recommendation(evidence=["```python\nsource inconnue", "missing.py:9"])

    recommendations.publish(project, [item], confirmed=True)

    warning = MarkdownIt().render(bodies[0]).split("<h3>Preuves non vérifiées</h3>", 1)[1]
    assert "<pre>" not in warning
    assert "format de référence non reconnu" in warning
    assert "missing.py:9" in warning
    assert "fichier introuvable" in warning


@pytest.mark.parametrize("field", ["reasons", "tradeoffs", "first_steps", "evidence"])
@pytest.mark.parametrize("marker", ["```", "~~~"])
def test_indented_fence_does_not_hide_published_warnings(publication, field, marker):
    project, bodies = publication
    item = recommendation(
        **{field: [f"  {marker}python\nexample.py:999\n{marker}"]},
        proposal="Voir missing.py:9.",
    )

    recommendations.publish(project, [item], confirmed=True)

    assert "<h3>Preuves non vérifiées</h3>" in MarkdownIt().render(bodies[0])


def test_valid_published_evidence_does_not_raise_a_warning(publication):
    project, bodies = publication

    recommendations.publish(project, [recommendation()], confirmed=True)

    assert "Preuves non vérifiées" not in bodies[0]
    assert "codearcheo:recommendation:" in bodies[0]


@pytest.mark.parametrize("indentation", ["", "  "])
@pytest.mark.parametrize("marker", ["```", "~~~"])
@pytest.mark.parametrize(("container", "continuation"), [
    ("", ""), ("> ", "> "), ("- ", "  "), ("1. ", "   "), ("> - ", ">   "),
])
def test_task_starting_with_a_fence_renders_its_code_and_following_text(
    publication, indentation, marker, container, continuation,
):
    project, bodies = publication
    item = recommendation(
        first_steps=[
            f"{indentation}{container}{marker}python\n"
            f"{indentation}{continuation}print(1)\n"
            f"{indentation}{continuation}{marker}\n\nVérifier le résultat.",
        ],
        proposal="Voir missing.py:9.",
    )

    recommendations.publish(project, [item], confirmed=True)

    rendered = MarkdownIt().render(bodies[0])
    assert '<pre><code class="language-python">print(1)\n</code></pre>' in rendered
    assert "<p>Vérifier le résultat.</p>" in rendered
    assert "<h3>Preuves non vérifiées</h3>" in rendered
    assert "[ ] Exemple" in rendered


def test_task_starting_with_a_tab_indented_nested_fence(publication):
    project, bodies = publication
    item = recommendation(
        first_steps=[
            "- \t> ~~~python\n    > print(1)\n    > ~~~\n\nVérifier le résultat.",
            "Confirmer le résultat.",
        ],
        proposal="Voir missing.py:9.",
    )

    recommendations.publish(project, [item], confirmed=True)

    rendered = MarkdownIt().render(bodies[0])
    assert '<pre><code class="language-python">print(1)\n</code></pre>' in rendered
    assert "<p>Vérifier le résultat.</p>" in rendered
    assert "<li>\n<p>[ ] Confirmer le résultat.</p>" in rendered
    assert "<h3>Preuves non vérifiées</h3>" in rendered


def test_review_records_json_and_sorts_plan(project, monkeypatch):
    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        record.call(recommendation(title="Second", impact="low").model_dump())
        record.call(recommendation(title="First").model_dump())
        return "Deux améliorations possibles."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    report = features.review(session)
    assert report.index("## First") < report.index("## Second")
    assert [r.title for r in session.store.load_recommendations()] == ["First", "Second"]
    assert "citation(s) vérifiée(s)" in report


def test_review_cli_focuses_on_the_selected_directory(project, monkeypatch):
    monkeypatch.setenv("LEARN_IT_BACKEND", "api")
    (project.root / "src").mkdir()
    (project.root / "src/app.py").write_text("app = None\n")

    def fake(system, task, tools, settings, on_tool=None):
        assert 'project-relative path "src"' in task
        assert "cite evidence from it" in task
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        record.call(recommendation(evidence=["src/app.py:1"]).model_dump())
        return "Revue du code applicatif."

    monkeypatch.setattr(features, "run_agent", fake)
    result = CliRunner().invoke(cli.app, [
        "review", "-p", str(project.root), "--path", "./src/",
    ])
    assert result.exit_code == 0, result.output
    report = (project.root / ".codearcheo/review.md").read_text()
    assert '    "src"' in report
    assert "src/app.py:1" in report


@pytest.mark.parametrize("path", ["src", "src/module.py"])
def test_scoped_review_requires_verifiable_evidence_in_scope(project, monkeypatch, path):
    for directory in ("src", "src_other"):
        (project.root / directory).mkdir()
        (project.root / directory / "module.py").write_text("value = 1\n")

    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        for reference in ("src_other/module.py:1", "src/module.py:2"):
            with pytest.raises(ToolError, match="verifiable citation"):
                record.call(recommendation(evidence=[reference]).model_dump())
        record.call(recommendation(evidence=["src/module.py:1", "app.py:1"]).model_dump())
        return "Revue ciblée."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    features.review(session, path=path)
    assert len(session.store.load_recommendations()) == 1


def test_scoped_review_accepts_a_quoted_path_with_spaces(project, monkeypatch):
    (project.root / "service client.py").write_text("value = 1\n")
    (project.root / "client.py").write_text("value = 2\n")

    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        record.call(recommendation(evidence=["`service client.py:1`"]).model_dump())
        return "Revue ciblée."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    report = features.review(session, path="service client.py")
    assert "1 citation(s) vérifiée(s), 0 introuvable(s)" in report


def test_scoped_review_does_not_use_the_suffix_of_a_quoted_path(project, monkeypatch):
    (project.root / "service app.py").write_text("value = 1\n")

    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        with pytest.raises(ToolError, match="verifiable citation"):
            record.call(recommendation(evidence=["`service app.py:1`"]).model_dump())
        record.call(recommendation(evidence=["`app.py:1`"]).model_dump())
        return "Revue ciblée."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    features.review(session, path="app.py")
    assert len(session.store.load_recommendations()) == 1


@pytest.mark.parametrize("path", ["app", ".env", "../shop", "/tmp", "alias"])
def test_inaccessible_review_path_stops_before_generation(project, monkeypatch, path):
    (project.root / "alias").symlink_to(project.root / "app.py")
    def unexpected(*args, **kwargs):
        pytest.fail("unexpected model call")

    monkeypatch.setattr(features, "run_agent", unexpected)
    result = CliRunner().invoke(cli.app, ["review", "-p", str(project.root), "--path", path])
    assert result.exit_code == 1
    assert "Périmètre de revue inaccessible" in result.output


def test_publication_never_happens_without_confirmation(project, monkeypatch):
    def forbidden(*args):
        pytest.fail("A network call was made without confirmation")

    monkeypatch.setattr(recommendations, "_gh", forbidden)
    with pytest.raises(ValueError, match="confirmation"):
        recommendations.publish(project, [recommendation()])


def test_an_improvement_must_have_an_actionable_first_step():
    with pytest.raises(ValueError, match="proposal"):
        recommendation(first_steps=[])
    with pytest.raises(ValueError, match="blank"):
        recommendation(evidence=[""])


def test_a_prose_only_review_never_erases_previous_recommendations(project, monkeypatch):
    from codearcheo.agent.runner import AgentError

    store = Store(project.root)
    store.save_recommendations([recommendation()])
    monkeypatch.setattr(features, "run_agent", lambda *args, **kwargs: "Just prose.")
    with pytest.raises(AgentError, match="aucune recommandation"):
        features.review(Session(project, scan(project), store, Settings()))
    assert len(store.load_recommendations()) == 1


def test_publication_deduplicates_and_skips_keep_verdict(project, monkeypatch):
    calls = []
    item = recommendation()
    project = replace(project, origin="https://github.com/owner/repo")

    def fake(*args):
        calls.append(args)
        if args[1] == "list":
            return json.dumps([{"body": recommendations._marker(item), "url": "existing"}])
        pytest.fail("Should reuse the existing issue")

    monkeypatch.setattr(recommendations, "_gh", fake)
    assert recommendations.publish(
        project, [item, recommendation(title="Keep", verdict="keep")], confirmed=True
    ) == ["existing"]
    assert len(calls) == 1


def test_scoped_review_completes_a_name_unique_within_its_scope(project, monkeypatch):
    for directory in ("src", "src_other"):
        (project.root / directory).mkdir()
        (project.root / directory / "module.py").write_text("value = 1\n")

    def fake(system, task, tools, settings, on_tool=None):
        record = next(t for t in tools if getattr(t, "name", "") == "record_recommendation")
        with pytest.raises(ToolError, match="verifiable citation"):
            record.call(recommendation(
                evidence=["Voir src_other/module.py:1. Dans ce fichier, voir module.py:1."],
            ).model_dump())
        record.call(recommendation(evidence=["module.py:1"]).model_dump())
        return "Voir module.py:1."

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    report = features.review(session, path="src")

    assert session.store.load_recommendations()[0].evidence == ["src/module.py:1"]
    assert "Voir src/module.py:1." in report
    assert "0 introuvable(s)" in report
