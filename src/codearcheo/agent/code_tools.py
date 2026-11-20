"""Syntax exploration tools shared by the Claude agent and MCP through ProjectTools."""

from __future__ import annotations

import json
from pathlib import Path

from anthropic.lib.tools import ToolError

from codearcheo.analyzers import code, inventory


def _result(value: dict) -> str:
    # Compact: the model reads it as well, and more of a large result fits under the cap.
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 20_000 else text[:20_000] + "\n… narrow the symbol or module."


class CodeTools:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _code_graph(self) -> code.CodeGraph:
        graph = code.analyze(self.root)
        if graph is None:
            raise ToolError("Syntax tools need the code extra: uv tool install 'codearcheo[code]'.")
        return graph

    def find_symbol(self, name: str, limit: int = 20) -> str:
        """Find classes/functions/types and candidate usages in one call using syntax trees.

        Args:
            name: Exact identifier or qualified name, e.g. 'Session' or 'Session.run'.
            limit: Maximum definitions and lexical usage candidates per result, capped at 100.
        """
        if not name.strip():
            raise ToolError("Provide a symbol name.")
        graph = self._code_graph()
        limit = max(1, min(limit, 100))
        identifier = name.rsplit(".", 1)[-1]
        definitions, references = [], []
        for module in graph.modules.values():
            definitions.extend(item.model_dump() for item in module.symbols
                               if name in {item.name, item.qualified_name})
            aliases = {alias for alias, original in module.aliases.items()
                       if original.rsplit(".", 1)[-1] == identifier}
            references.extend(item.model_dump() for item in module.references
                              if item.name in {identifier, *aliases})
        return _result({"definitions": definitions[:limit], "usages": references[:limit],
                        "definition_count": len(definitions), "usage_count": len(references),
                        "usage_resolution": "lexical identifier/import-alias candidates; "
                                            "bindings and shadowing are not resolved",
                        "skipped_files": graph.skipped})

    def module_dependencies(self, path: str) -> str:
        """Read actual static imports, resolved internal dependencies and reverse dependents.

        Args:
            path: Project-relative source file, e.g. 'src/app.py' or 'src/routes.ts'.
        """
        if not inventory.is_safe_path(self.root, path):
            raise ToolError("Module path is outside the allowed inventory.")
        graph = self._code_graph()
        module = graph.modules.get(path.removeprefix("./"))
        if module is None:
            raise ToolError("No parsed module at this path; inspect list_files and graph limits.")
        return _result({"module": module.path,
                        "imports": [item.model_dump() for item in module.imports],
                        "dependencies": sorted({target for item in module.imports
                                                for target in item.resolved}),
                        "dependents": [source for source, target in graph.edges()
                                       if target == module.path],
                        "syntax_errors": module.syntax_errors})
