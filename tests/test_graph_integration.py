import json

import pytest
from typer.testing import CliRunner

from learn_it import features
from learn_it.agent.tools import ProjectTools
from learn_it.analyzers import code, scan
from learn_it.cli import app
from learn_it.config import Settings
from learn_it.features import Session
from learn_it.store import Store

pytestmark = pytest.mark.skipif(not code.available(), reason="optional code extra")


def test_overview_keeps_only_the_real_import_diagram(project, monkeypatch):
    seen = []

    def fake(system, task, tools, settings, on_tool=None):
        seen.append(task)
        return "```mermaid\ngraph TD\n INVENTED-->OTHER\n```\n```mermaid\nBAD-->EDGE\n```"

    monkeypatch.setattr(features, "run_agent", fake)
    session = Session(project, scan(project), Store(project.root), Settings())
    report = features.overview(session)
    diagram = code.analyze(project.root).mermaid()
    assert diagram in seen[0]
    assert diagram in report
    assert "INVENTED" not in report and "BAD-->EDGE" not in report
    assert report.count("```mermaid") == 1
    assert (session.store.dir / "overview.md").read_text() == report


def test_syntax_tools_are_exposed_to_the_agent(project):
    tools = ProjectTools(project.root)
    names = {fn.__name__ for fn in tools.exploration()}
    assert {"find_symbol", "module_dependencies"} <= names
    assert json.loads(tools.module_dependencies("app.py"))["module"] == "app.py"


def test_scan_graph_json_is_a_reusable_graph(project):
    result = CliRunner().invoke(app, ["scan", str(project.root), "--graph-json"])
    assert result.exit_code == 0, result.output
    graph = json.loads(result.stdout)
    assert "modules" in graph and "edges" in graph
