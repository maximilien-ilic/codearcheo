import json

import pytest
from anthropic.lib.tools import ToolError

from learn_it.agent.code_tools import CodeTools
from learn_it.analyzers import code, scan
from learn_it.domain import Hotspot
from learn_it.sources import Project

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_python")


@pytest.fixture
def code_project(tmp_path):
    root = tmp_path / "project"
    fixtures = {
        "python/app.py": "from .helper import run as execute\nclass App:\n"
                         "    def call(self):\n        return execute()\n"
                         "if __name__ == '__main__':\n    App().call()\n",
        "python/helper.py": "def run():\n    return 1\n",
        "js/main.js": "const helper = require('./helper');\nexport class App {}\n"
                      "export function main() {return helper.run()}\n",
        "js/helper.js": "exports.run = () => 1;\n",
        "ts/main.ts": "import {run as execute} from './helper.js';\n"
                      "export interface Port {name: string}\n"
                      "export function main() {return execute()}\n",
        "ts/helper.ts": "export const run = () => 1;\n",
        "go/go.mod": "module example.com/demo\n\ngo 1.22\n",
        "go/main.go": 'package main\nimport "example.com/demo/helper"\n'
                      'func main() { helper.Run() }\n',
        "go/helper/helper.go": "package helper\ntype App struct {}\n"
                               "func Run() int {return 1}\n",
        "go/helper/helper_test.go": "package helper\nfunc TestRun() {}\n",
        "rust/src/main.rs": "mod helper;\nuse crate::helper::run;\n"
                            "struct App {}\nimpl App {fn new() -> Self {App {}}}\n"
                            "fn main() {run();}\n",
        "rust/src/helper.rs": "pub fn run() -> u32 {1}\n",
    }
    for name, text in fixtures.items():
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    return root


@pytest.mark.parametrize("language,main,dependency,symbol", [
    ("python", "python/app.py", "python/helper.py", "App.call"),
    ("javascript", "js/main.js", "js/helper.js", "App"),
    ("typescript", "ts/main.ts", "ts/helper.ts", "Port"),
    ("go", "go/main.go", "go/helper/helper.go", "main"),
    ("rust", "rust/src/main.rs", "rust/src/helper.rs", "App.new"),
])
def test_every_language_extracts_symbols_and_real_import_edges(code_project, language,
                                                               main, dependency, symbol):
    if code._parser(language) is None:
        pytest.skip(f"optional {language} grammar is not installed")
    graph = code.analyze(code_project)
    module = graph.modules[main]
    assert module.language == language
    assert symbol in {item.qualified_name for item in module.symbols}
    assert (main, dependency) in graph.edges()
    if language == "go":
        assert (main, "go/helper/helper_test.go") not in graph.edges()


def test_symbol_tool_returns_definitions_and_alias_usage_in_one_call(code_project):
    tools = CodeTools(code_project)
    result = json.loads(tools.find_symbol("run"))
    assert any(item["path"] == "python/helper.py" for item in result["definitions"])
    assert any(item["qualified_name"] == "exports.run" for item in result["definitions"])
    assert any(item["name"] == "execute" and item["path"] == "python/app.py"
               for item in result["usages"])
    assert "lexical" in result["usage_resolution"]
    module = json.loads(tools.module_dependencies("python/helper.py"))
    assert "python/app.py" in module["dependents"]
    assert json.loads(tools.module_dependencies("python/app.py"))["dependencies"] == [
        "python/helper.py"
    ]


def test_graph_mermaid_export_summary_and_worktree_changes_are_deterministic(code_project):
    graph = code.analyze(code_project)
    summary = graph.summary([Hotspot(path="python/helper.py", commits=9)])
    assert summary.modules == len(graph.modules)
    assert "go/main.go" in summary.entry_points
    risk = next(item for item in summary.risky_modules if item.path == "python/helper.py")
    assert risk.churn == 9 and risk.risk_score == 9
    payload = json.loads(graph.export_json())
    assert {"source": "python/app.py", "target": "python/helper.py"} in payload["edges"]
    assert graph.mermaid() == code.analyze(code_project).mermaid()
    assert "python/helper.py" in graph.mermaid()
    assert "subset:" in graph.mermaid(max_modules=2)
    (code_project / "python/app.py").write_text("class Changed:\n    pass\n")
    refreshed = code.analyze(code_project)
    assert ("python/app.py", "python/helper.py") not in refreshed.edges()
    assert refreshed.modules["python/app.py"].symbols[0].name == "Changed"


def test_unresolved_external_dynamic_and_ambiguous_imports_do_not_fabricate_edges(tmp_path):
    (tmp_path / "app.py").write_text("import requests\nimport helper\n")
    (tmp_path / "helper.py").write_text("def first(): pass\n")
    (tmp_path / "helper").mkdir()
    (tmp_path / "helper/__init__.py").write_text("def second(): pass\n")
    graph = code.analyze(tmp_path)
    assert graph.edges() == []
    assert {item.module for item in graph.modules["app.py"].imports} == {"requests", "helper"}


def test_python_relative_import_cannot_escape_above_the_top_level_package(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/a.py").write_text("from ..utils import run\n")
    (tmp_path / "utils.py").write_text("def run(): pass\n")
    assert code.analyze(tmp_path).edges() == []


def test_javascript_require_prefers_javascript_over_a_sibling_typescript_file(tmp_path):
    if code._parser("javascript") is None or code._parser("typescript") is None:
        pytest.skip("optional JS and TS grammars")
    (tmp_path / "main.js").write_text("const util = require('./util');\n")
    (tmp_path / "util.js").write_text("exports.run = () => 1;\n")
    (tmp_path / "util.ts").write_text("export const run = () => 2;\n")
    assert code.analyze(tmp_path).edges() == [("main.js", "util.js")]
    (tmp_path / "util.js").unlink()
    (tmp_path / "main.js").write_text("const util = require('./util.js');\n")
    assert code.analyze(tmp_path).edges() == []


def test_rust_super_import_cannot_escape_above_the_crate_root(tmp_path):
    if code._parser("rust") is None:
        pytest.skip("optional Rust grammar")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/lib.rs").write_text("mod foo;\n")
    (tmp_path / "src/foo.rs").write_text("use super::super::outside::Thing;\n")
    (tmp_path / "outside.rs").write_text("pub struct Thing;\n")
    graph = code.analyze(tmp_path)
    assert ("src/lib.rs", "src/foo.rs") in graph.edges()
    assert ("src/foo.rs", "outside.rs") not in graph.edges()


def test_inventory_safety_size_bounds_and_syntax_errors_are_preserved(code_project, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("def PRIVATE_CANARY(): pass\n")
    (code_project / "linked.py").symlink_to(outside)
    # Explicit file lists do not bypass the safe path policy.
    graph = code.analyze(code_project, ["linked.py", "../outside.py", "python/app.py"])
    assert set(graph.modules) == {"python/app.py"}
    (code_project / "huge.py").write_bytes(b" " * (code.MAX_FILE_BYTES + 1))
    (code_project / "broken.py").write_text("def broken(:\n")
    graph = code.analyze(code_project)
    assert "huge.py" in graph.skipped
    assert graph.modules["broken.py"].syntax_errors
    for path in ("../outside.py", "linked.py", ".env"):
        with pytest.raises(ToolError):
            CodeTools(code_project).module_dependencies(path)


def test_scan_profile_contains_summary_without_all_symbol_references(code_project):
    profile = scan(Project(code_project, "code"))
    assert profile.code_structure.modules > 0
    assert profile.code_structure.symbols > 0
    assert "references" not in profile.code_structure.model_dump()


def test_grouped_rust_imports_and_aliases_are_real_edges(code_project):
    main = code_project / "rust/src/main.rs"
    main.write_text("use crate::{helper::{self, run as execute}};\n"
                    "fn main() {execute();}\n")
    graph = code.analyze(code_project)
    assert ("rust/src/main.rs", "rust/src/helper.rs") in graph.edges()
    usages = json.loads(CodeTools(code_project).find_symbol("run"))["usages"]
    assert any(item["name"] == "execute" and item["path"] == "rust/src/main.rs"
               for item in usages)


def test_mermaid_escapes_arbitrary_source_filenames(tmp_path):
    filename = 'odd"]\nunsafe.py'
    (tmp_path / filename).write_text("class App: pass\n")
    diagram = code.analyze(tmp_path).mermaid()
    assert filename not in diagram
    assert "&quot;" in diagram and "&#10;" in diagram
