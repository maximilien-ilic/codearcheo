"""Tree-sitter symbol inventory and conservative internal import graph.

Install the optional `code` extra for Python, JavaScript/TypeScript, Go and Rust. Modules
from the analysed project are never imported. Edges only reference files actually present
in the safe inventory; unresolved external or ambiguous imports are retained as imports.
"""

from __future__ import annotations

import hashlib
import html
import importlib
import importlib.metadata
import json
import re
from contextlib import suppress
from functools import lru_cache
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field, ValidationError

from learn_it.analyzers import inventory
from learn_it.code_models import CodeSummary, Import, Module, ModuleRank, Reference, Symbol

EXTENSIONS = {".py": "python", ".js": "javascript", ".jsx": "javascript",
              ".mjs": "javascript", ".cjs": "javascript", ".ts": "typescript",
              ".tsx": "tsx", ".go": "go", ".rs": "rust"}
MAX_FILE_BYTES = 1_000_000
MAX_PROJECT_BYTES = 50_000_000
MAX_FILES = 10_000
MAX_NODES = 100_000
_SYMBOLS = {
    "class_definition": "class", "function_definition": "function",
    "class_declaration": "class", "function_declaration": "function",
    "generator_function_declaration": "function", "method_definition": "method",
    "interface_declaration": "interface", "type_alias_declaration": "type",
    "method_declaration": "method", "type_spec": "type", "function_item": "function",
    "struct_item": "struct", "enum_item": "enum", "trait_item": "trait",
}


@lru_cache(maxsize=6)
def _language(language: str):
    try:
        from tree_sitter import Language

        package = "typescript" if language == "tsx" else language
        grammar = importlib.import_module(f"tree_sitter_{package}")
        factory_name = f"language_{language}" if package == "typescript" else "language"
        return Language(getattr(grammar, factory_name)())
    except ImportError:
        return None


def _parser(language: str):
    grammar = _language(language)
    if grammar is None:
        return None
    from tree_sitter import Parser

    # Parser is mutable; independent instances make concurrent MCP calls safe.
    return Parser(grammar)


def available() -> bool:
    return _parser("python") is not None


def _text(node, data: bytes) -> str:
    return data[node.start_byte:node.end_byte].decode("utf-8", errors="replace") if node else ""


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) > 1 and value[0] in {'"', "'", "`"} else value


def _rust_uses(node, data: bytes, aliases: dict[str, str], prefix: str = "") -> list[str]:
    if node.type == "use_list":
        return [value for child in node.named_children
                for value in _rust_uses(child, data, aliases, prefix)]
    if node.type == "scoped_use_list":
        path = _text(node.child_by_field_name("path"), data)
        return _rust_uses(node.child_by_field_name("list"), data, aliases,
                          prefix + path + "::")
    if node.type == "use_as_clause":
        path = _text(node.child_by_field_name("path"), data)
        alias = _text(node.child_by_field_name("alias"), data)
        aliases[alias] = (prefix + path).replace("::", ".")
        return [prefix + path]
    name = _text(node, data)
    return [prefix.rstrip(":") if name == "self" and prefix else prefix + name]


def _imports(node, data: bytes, module: Module) -> list[Import]:
    language = module.language
    line = node.start_point.row + 1
    if language == "python" and node.type == "import_statement":
        result = []
        for child in node.named_children:
            name = child.child_by_field_name("name") if child.type == "aliased_import" else child
            result.append(Import(module=_text(name, data), line=line))
        return result
    if language == "python" and node.type == "import_from_statement":
        source = _text(node.child_by_field_name("module_name"), data)
        names = []
        for child in node.children_by_field_name("name"):
            name = child.child_by_field_name("name") if child.type == "aliased_import" else child
            original = _text(name, data)
            alias = _text(child.child_by_field_name("alias"), data) or original
            names.append(original)
            module.aliases[alias] = f"{source}.{original}"
        return [Import(module=source, names=names, line=line)]
    if language in {"javascript", "typescript", "tsx"}:
        source = node.child_by_field_name("source")
        if node.type in {"import_statement", "export_statement"} and source:
            return [Import(module=_unquote(_text(source, data)), line=line)]
        if node.type == "call_expression":
            function = _text(node.child_by_field_name("function"), data)
            args = node.child_by_field_name("arguments")
            if function in {"require", "import"} and args and args.named_children:
                argument = args.named_children[0]
                if argument.type == "string":
                    return [Import(module=_unquote(_text(argument, data)), line=line)]
        if node.type == "import_specifier":
            name = _text(node.child_by_field_name("name"), data)
            alias = _text(node.child_by_field_name("alias"), data) or name
            module.aliases[alias] = name
    if language == "go" and node.type == "import_spec":
        return [Import(module=_unquote(_text(node.child_by_field_name("path"), data)), line=line)]
    if language == "rust":
        if node.type == "mod_item" and node.child_by_field_name("body") is None:
            return [Import(module="self::" + _text(node.child_by_field_name("name"), data),
                           line=line)]
        if node.type == "use_declaration":
            argument = node.child_by_field_name("argument")
            return [Import(module=value, line=line)
                    for value in _rust_uses(argument, data, module.aliases)]
    return []


def _parse(path: str, language: str, data: bytes) -> Module | None:
    parser = _parser(language)
    if parser is None:
        return None
    tree = parser.parse(data)
    module = Module(path=path, language=language, syntax_errors=tree.root_node.has_error)
    stack = [(tree.root_node, ())]
    visited = 0
    while stack:
        node, scope = stack.pop()
        visited += 1
        if visited > MAX_NODES:
            raise ValueError("syntax tree exceeds node budget")
        imports = _imports(node, data, module)
        module.imports.extend(imports)
        kind = _SYMBOLS.get(node.type)
        if node.type == "impl_item":
            implementation = _text(node.child_by_field_name("type"), data)
            if implementation:
                scope = (*scope, implementation)
        name_node = node.child_by_field_name("name")
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value and value.type in {"arrow_function", "function_expression"}:
                kind = "function"
        if node.type == "assignment_expression":
            value = node.child_by_field_name("right")
            target = node.child_by_field_name("left")
            if (value and value.type in {"arrow_function", "function_expression"}
                    and target and target.type in {"identifier", "member_expression"}):
                kind, name_node = "function", target
        if kind and name_node:
            name = _text(name_node, data)
            module.symbols.append(Symbol(name=name.rsplit(".", 1)[-1],
                                         qualified_name=".".join((*scope, name)),
                                         kind=kind, path=path, line=node.start_point.row + 1,
                                         end_line=node.end_point.row + 1))
            if name in {"main", "__main__"}:
                module.entry_point = True
            scope = (*scope, name)
        if language == "python" and node.type == "if_statement":
            condition = _text(node.child_by_field_name("condition"), data)
            module.entry_point |= "__name__" in condition and "__main__" in condition
        if node.type in {"identifier", "property_identifier", "field_identifier",
                         "type_identifier"}:
            parent = node.parent
            is_name = parent and parent.child_by_field_name("name") == node and (
                parent.type in _SYMBOLS or parent.type == "variable_declarator"
            )
            if not is_name:
                module.references.append(Reference(name=_text(node, data), path=path,
                                                   line=node.start_point.row + 1))
        stack.extend((child, scope) for child in reversed(node.named_children))
    module.imports = list({(item.module, item.line): item for item in module.imports}.values())
    return module


class CodeGraph(BaseModel):
    modules: dict[str, Module] = Field(default_factory=dict)
    skipped: dict[str, str] = Field(default_factory=dict)

    def edges(self) -> list[tuple[str, str]]:
        return sorted({(path, target) for path, module in self.modules.items()
                       for item in module.imports for target in item.resolved if path != target})

    def summary(self, hotspots=()) -> CodeSummary:
        churn = {item.path: item.commits for item in hotspots}
        incoming, outgoing = {}, {}
        edges = self.edges()
        for source, target in edges:
            outgoing[source] = outgoing.get(source, 0) + 1
            incoming[target] = incoming.get(target, 0) + 1
        ranks = [ModuleRank(path=path, incoming=incoming.get(path, 0),
                            outgoing=outgoing.get(path, 0), churn=churn.get(path, 0),
                            risk_score=(incoming.get(path, 0) + outgoing.get(path, 0))
                            * churn.get(path, 0)) for path in self.modules]
        central = sorted(ranks, key=lambda item: (-item.incoming - item.outgoing, item.path))
        risky = sorted((item for item in ranks if item.risk_score),
                       key=lambda item: (-item.risk_score, item.path))
        return CodeSummary(modules=len(self.modules),
                           symbols=sum(len(item.symbols) for item in self.modules.values()),
                           internal_edges=len(edges), central_modules=central[:10],
                           entry_points=[path for path, item in self.modules.items()
                                         if item.entry_point][:20], risky_modules=risky[:10],
                           skipped=dict(list(self.skipped.items())[:20]))

    def mermaid(self, max_modules: int = 60) -> str:
        ranked = self.summary().central_modules
        paths = sorted(self.modules)
        if len(paths) > max_modules:
            selected = [item.path for item in ranked]
            paths = sorted(list(dict.fromkeys([*selected, *paths]))[:max_modules])
        ids = {path: f"m{index}" for index, path in enumerate(paths)}
        lines = ["flowchart LR"]
        if len(paths) < len(self.modules):
            lines.append(f"  %% subset: {len(paths)} of {len(self.modules)} modules")
        for path in paths:
            label = html.escape(path, quote=True).replace("\n", "&#10;").replace("\r", "&#13;")
            label = label.replace("`", "&#96;")
            lines.append(f'  {ids[path]}["{label}"]')
        lines += [f"  {ids[source]} --> {ids[target]}" for source, target in self.edges()
                  if source in ids and target in ids]
        return "\n".join(lines)

    def export_json(self, indent: int = 2) -> str:
        payload = self.model_dump()
        payload["edges"] = [{"source": source, "target": target}
                            for source, target in self.edges()]
        return json.dumps(payload, ensure_ascii=False, indent=indent)


def _python_names(path: str) -> list[str]:
    parts = PurePosixPath(path).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = [".".join(parts)]
    if "src" in parts:
        names.append(".".join(parts[parts.index("src") + 1:]))
    return names


def _resolve(graph: CodeGraph, root: Path, files: list[str]) -> None:
    python_names = {}
    go_roots = []
    for path, module in graph.modules.items():
        if module.language == "python":
            for name in _python_names(path):
                python_names.setdefault(name, []).append(path)
    for path in files:
        if PurePosixPath(path).name == "go.mod":
            try:
                if (root / path).stat().st_size > 100_000:
                    continue
                data = (root / path).read_text(encoding="utf-8")[:100_000]
            except (OSError, UnicodeError):
                continue
            if match := re.search(r"(?m)^\s*module\s+([^\s]+)", data):
                go_roots.append((PurePosixPath(path).parent, match[1]))
    # Computed once: per import, these lookups used to scan every module of the project
    # (millions of path operations on golang/go).
    go_roots.sort(key=lambda entry: -len(entry[0].parts))
    go_packages: dict[str, list[str]] = {}
    for path, value in graph.modules.items():
        if value.language == "go" and not path.endswith("_test.go"):
            go_packages.setdefault(PurePosixPath(path).parent.as_posix(), []).append(path)
    for source, module in graph.modules.items():
        go_root = None
        if module.language == "go":
            go_root = next((entry for entry in go_roots
                            if entry[0].parts == () or source.startswith(f"{entry[0]}/")), None)
        for item in module.imports:
            targets = []
            if module.language == "python":
                name = item.module
                if name.startswith("."):
                    dots = len(name) - len(name.lstrip("."))
                    package = _python_names(str(PurePosixPath(source).parent / "__init__.py"))
                    bases = [base.split(".") for base in package if base]
                    names = [".".join([*base[:len(base) - dots + 1], name.lstrip(".")]).strip(".")
                             for base in bases if dots <= len(base)]
                else:
                    names = [name]
                for name in names:
                    candidates = [name, *(f"{name}.{child}".strip(".") for child in item.names)]
                    for candidate in candidates:
                        found = python_names.get(candidate, [])
                        if len(found) == 1:
                            targets.extend(found)
            elif module.language in {"javascript", "typescript", "tsx"}:
                if item.module.startswith("."):
                    candidate = (root / source).parent / item.module
                    try:
                        relative = candidate.resolve().relative_to(root.resolve()).as_posix()
                    except (OSError, ValueError):
                        continue
                    variants = [relative]
                    suffixes = (
                        (".js", ".jsx", ".mjs", ".cjs") if module.language == "javascript"
                        else (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
                    )
                    variants += [relative + suffix for suffix in suffixes]
                    variants += [relative + "/index" + suffix for suffix in suffixes]
                    if module.language in {"typescript", "tsx"} and relative.endswith(".js"):
                        variants.append(relative[:-3] + ".ts")
                    targets = next(([path] for path in variants if path in graph.modules), [])
            elif module.language == "go" and go_root is not None:
                directory, prefix = go_root
                if item.module == prefix or item.module.startswith(prefix + "/"):
                    package = directory / item.module.removeprefix(prefix).lstrip("/")
                    targets = list(go_packages.get(package.as_posix(), []))
            elif module.language == "rust" and "{" not in item.module:
                value = item.module.replace(" ", "")
                if value.startswith(("crate::", "self::", "super::")):
                    parts = list(PurePosixPath(source).parent.parts)
                    crate_root = parts[:parts.index("src") + 1] if "src" in parts else []
                    if value.startswith("crate::"):
                        parts = crate_root.copy()
                    elif PurePosixPath(source).stem not in {"lib", "main", "mod"}:
                        parts.append(PurePosixPath(source).stem)
                    while value.startswith("super::"):
                        if len(parts) <= len(crate_root):
                            parts = []
                            break
                        parts = parts[:-1]
                        value = value[len("super::"):]
                    if value.startswith("super::"):
                        continue
                    value = value.removeprefix("crate::").removeprefix("self::")
                    segments = value.split("::")
                    while segments:
                        base = PurePosixPath(*parts, *segments).as_posix()
                        matches = [path for path in (base + ".rs", base + "/mod.rs")
                                   if path in graph.modules]
                        if matches:
                            targets = matches
                            break
                        segments.pop()
            item.resolved = sorted(set(targets))


_CACHE_FILE = "code-cache.json"


@lru_cache(maxsize=1)
def _cache_version() -> str:
    """Parsing results stay valid only for the same parser and grammar versions."""
    packages = ["tree-sitter", *(f"tree-sitter-{name}" for name in
                                 ("python", "javascript", "typescript", "go", "rust"))]
    versions = []
    for package in packages:
        try:
            versions.append(f"{package}={importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            versions.append(f"{package}=-")
    return "1;" + ",".join(versions)


def _load_cache(root: Path) -> dict[str, dict]:
    from learn_it.store import Store

    try:
        data = Store(root).load_json(_CACHE_FILE)
    except OSError:  # symlinked store: no cache rather than following it
        return {}
    if not isinstance(data, dict) or data.get("version") != _cache_version():
        return {}
    modules = data.get("modules")
    return modules if isinstance(modules, dict) else {}


def _save_cache(root: Path, modules: dict[str, dict]) -> None:
    from learn_it.store import Store

    # A read-only checkout or a refused symlink only costs the optimisation.
    with suppress(OSError):
        Store(root).save_json(_CACHE_FILE, {"version": _cache_version(), "modules": modules})


def analyze(root: Path, files: list[str] | None = None) -> CodeGraph | None:
    """Build a bounded graph from the current safe worktree; None means extra not installed."""
    if not available():
        return None
    root = root.resolve()
    files = sorted(path for path in set(files if files is not None else inventory.list_files(root))
                   if inventory.is_safe_path(root, path))
    graph = CodeGraph()
    total_bytes = 0
    # Parsing dominates the scan of a large project (57 s on golang/go), so each module is
    # cached under a hash of its language and content: valid for uncommitted work too.
    cached = _load_cache(root)
    fresh: dict[str, dict] = {}
    for path in files:
        language = EXTENSIONS.get(PurePosixPath(path).suffix)
        if not language:  # `files` was filtered through is_safe_path just above
            continue
        try:
            if not (root / path).is_file():
                continue
            size = (root / path).stat().st_size
            if size > MAX_FILE_BYTES or size + total_bytes > MAX_PROJECT_BYTES:
                graph.skipped[path] = "source byte budget exceeded"
                continue
            if len(graph.modules) >= MAX_FILES:
                graph.skipped[path] = "source file budget exceeded"
                continue
            data = (root / path).read_bytes()
            total_bytes += len(data)
            key = hashlib.sha256(language.encode() + b"\0" + data).hexdigest()
            module = None
            entry = cached.get(key)
            if isinstance(entry, dict) and isinstance(entry.get("skipped"), str):
                # A refusal (node budget…) is as deterministic as a parse: don't redo it.
                fresh[key] = entry
                graph.skipped[path] = entry["skipped"]
                continue
            if entry is not None:
                try:
                    module = Module(path=path, **entry)
                    # Byte-identical files and renames share a cache entry.
                    for location in (*module.symbols, *module.references):
                        if location.path != path:
                            location.path = path
                    fresh[key] = entry  # already serialized: no need to dump it again
                except (TypeError, ValidationError):
                    module = None
            if module is None:
                try:
                    module = _parse(path, language, data)
                except ValueError as exc:
                    fresh[key] = {"skipped": str(exc)}
                    raise
                if module is not None:
                    fresh[key] = module.model_dump(exclude={"path"})
            if module is None:
                graph.skipped[path] = "language grammar is not installed"
            else:
                graph.modules[path] = module
        except (OSError, ValueError) as exc:
            graph.skipped[path] = str(exc)
    if fresh.keys() != cached.keys():
        _save_cache(root, fresh)
    _resolve(graph, root, files)
    return graph
