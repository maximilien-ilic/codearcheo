"""Detect the tech stack from manifests and config files. Deterministic: no LLM involved."""

from __future__ import annotations

import ast
import json
import re
import tokenize
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from fnmatch import fnmatch
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from codearcheo.domain import Technology, is_auxiliary_source

# Dependencies worth calling out because they are architectural choices, not utilities.
# Any other dependency found in a manifest is reported as a plain "library".
NOTABLE: dict[str, tuple[str, str]] = {
    # Python
    "django": ("Django", "framework"),
    "flask": ("Flask", "framework"),
    "fastapi": ("FastAPI", "framework"),
    "typer": ("Typer", "framework"),
    "click": ("Click", "framework"),
    "sqlalchemy": ("SQLAlchemy", "data"),
    "alembic": ("Alembic", "data"),
    "psycopg": ("PostgreSQL", "data"),
    "psycopg2": ("PostgreSQL", "data"),
    "psycopg2-binary": ("PostgreSQL", "data"),
    "asyncpg": ("PostgreSQL", "data"),
    "pymongo": ("MongoDB", "data"),
    "redis": ("Redis", "data"),
    "celery": ("Celery", "infra"),
    "pytest": ("pytest", "testing"),
    # JavaScript / TypeScript
    "typescript": ("TypeScript", "language"),
    "react": ("React", "ui"),
    "vue": ("Vue", "ui"),
    "svelte": ("Svelte", "ui"),
    "tailwindcss": ("Tailwind CSS", "ui"),
    "next": ("Next.js", "framework"),
    "nuxt": ("Nuxt", "framework"),
    "@sveltejs/kit": ("SvelteKit", "framework"),
    "@angular/core": ("Angular", "framework"),
    "express": ("Express", "framework"),
    "fastify": ("Fastify", "framework"),
    "@nestjs/core": ("NestJS", "framework"),
    "hono": ("Hono", "framework"),
    "prisma": ("Prisma", "data"),
    "@prisma/client": ("Prisma", "data"),
    "drizzle-orm": ("Drizzle", "data"),
    "typeorm": ("TypeORM", "data"),
    "mongoose": ("MongoDB", "data"),
    "pg": ("PostgreSQL", "data"),
    "mysql2": ("MySQL", "data"),
    "ioredis": ("Redis", "data"),
    "graphql": ("GraphQL", "api"),
    "@trpc/server": ("tRPC", "api"),
    "vite": ("Vite", "tooling"),
    "webpack": ("webpack", "tooling"),
    "jest": ("Jest", "testing"),
    "vitest": ("Vitest", "testing"),
    "@playwright/test": ("Playwright", "testing"),
    "cypress": ("Cypress", "testing"),
    # Go
    "github.com/gin-gonic/gin": ("Gin", "framework"),
    "github.com/labstack/echo/v4": ("Echo", "framework"),
    "github.com/gofiber/fiber/v2": ("Fiber", "framework"),
    "gorm.io/gorm": ("GORM", "data"),
    "github.com/jackc/pgx/v5": ("PostgreSQL", "data"),
    # Rust
    "tokio": ("Tokio", "framework"),
    "axum": ("Axum", "framework"),
    "actix-web": ("Actix Web", "framework"),
    "diesel": ("Diesel", "data"),
    "sqlx": ("SQLx", "data"),
    # AI
    "anthropic": ("Claude API", "ai"),
    "@anthropic-ai/sdk": ("Claude API", "ai"),
    "openai": ("OpenAI API", "ai"),
    "langchain": ("LangChain", "ai"),
    "torch": ("PyTorch", "ai"),
    "transformers": ("Hugging Face Transformers", "ai"),
    # JVM, Ruby, PHP and .NET
    "org.springframework.boot:spring-boot-starter": ("Spring Boot", "framework"),
    "org.springframework.boot:spring-boot-starter-web": ("Spring Boot", "framework"),
    "org.springframework:spring-webmvc": ("Spring MVC", "framework"),
    "org.springframework:spring-context": ("Spring", "framework"),
    "io.ktor:ktor-server-core": ("Ktor", "framework"),
    "org.jetbrains.kotlin:kotlin-stdlib": ("Kotlin", "language"),
    "org.hibernate.orm:hibernate-core": ("Hibernate", "data"),
    "org.junit.jupiter:junit-jupiter": ("JUnit", "testing"),
    "rails": ("Rails", "framework"),
    "sinatra": ("Sinatra", "framework"),
    "rspec": ("RSpec", "testing"),
    "sidekiq": ("Sidekiq", "infra"),
    "laravel/framework": ("Laravel", "framework"),
    "symfony/framework-bundle": ("Symfony", "framework"),
    "doctrine/orm": ("Doctrine ORM", "data"),
    "phpunit/phpunit": ("PHPUnit", "testing"),
    "microsoft.aspnetcore.app": ("ASP.NET Core", "framework"),
    "microsoft.net.sdk.web": ("ASP.NET Core", "framework"),
    "microsoft.entityframeworkcore": ("Entity Framework Core", "data"),
    "npgsql": ("PostgreSQL", "data"),
    "xunit": ("xUnit", "testing"),
}

# Container images (compose files) that reveal a backing service.
IMAGES: dict[str, tuple[str, str]] = {
    "postgres": ("PostgreSQL", "data"),
    "postgresql": ("PostgreSQL", "data"),
    "mysql": ("MySQL", "data"),
    "mariadb": ("MariaDB", "data"),
    "mongo": ("MongoDB", "data"),
    "redis": ("Redis", "data"),
    "elasticsearch": ("Elasticsearch", "data"),
    "minio": ("MinIO", "data"),
    "rabbitmq": ("RabbitMQ", "infra"),
    "kafka": ("Kafka", "infra"),
    "cp-kafka": ("Kafka", "infra"),
    "nginx": ("Nginx", "infra"),
}

# Files whose mere presence reveals a choice. Patterns with a "/" match the whole path.
FILE_SIGNALS: dict[str, tuple[str, str]] = {
    "Dockerfile": ("Docker", "infra"),
    "*.Dockerfile": ("Docker", "infra"),
    ".github/workflows/*": ("GitHub Actions", "ci"),
    ".gitlab-ci.yml": ("GitLab CI", "ci"),
    "Jenkinsfile": ("Jenkins", "ci"),
    "*.tf": ("Terraform", "infra"),
    "Chart.yaml": ("Helm", "infra"),
    "kustomization.yaml": ("Kubernetes", "infra"),
    "vercel.json": ("Vercel", "infra"),
    "netlify.toml": ("Netlify", "infra"),
    "fly.toml": ("Fly.io", "infra"),
    "serverless.yml": ("Serverless Framework", "infra"),
    "turbo.json": ("Turborepo", "tooling"),
    "nx.json": ("Nx", "tooling"),
    "pnpm-workspace.yaml": ("pnpm workspaces", "tooling"),
    ".pre-commit-config.yaml": ("pre-commit", "tooling"),
    "pom.xml": ("Maven", "tooling"),
    "build.gradle": ("Gradle", "tooling"),
    "build.gradle.kts": ("Gradle", "tooling"),
    "Gemfile": ("Ruby", "language"),
    "*.csproj": (".NET", "framework"),
}

# Plain PHP declares its database in code, not in a manifest: the PDO driver or mysqli.
_PHP_DATABASES = {
    "mysql": "MySQL", "pgsql": "PostgreSQL", "sqlite": "SQLite", "sqlsrv": "SQL Server",
    "oci": "Oracle",
}
_PHP_OPEN = re.compile(r"<\?(?:php(?=[\ \t\r\n]|\Z)|=)", re.IGNORECASE)
_PHP_IDENTIFIER = r"[A-Za-z_\x80-\U0010ffff][A-Za-z_0-9\x80-\U0010ffff]*"
# What can change the lexical state in PHP code, or reveal a database connection.
_PHP_CODE = re.compile(
    rf"""
    (?P<close>\?>) | (?P<line>//|\#(?!\[)) | (?P<block>/\*)
    | (?P<string>['"`])
    | <<<[\ \t]*(?P<hq>['"]?)(?P<label>{_PHP_IDENTIFIER})(?P=hq)(?:\r\n|[\r\n])
    | (?P<open>\{{) | (?P<shut>\}})
    | \bnew\s+\\?PDO\s*\(\s*(?=['"](?P<driver>mysql|pgsql|sqlite|sqlsrv|oci):)
    | (?P<mysqli>\bmysqli_connect\s*|\bnew\s+\\?mysqli\s*)\(
    """,
    re.VERBOSE,
)
_PHP_LINE_COMMENT = re.compile(r"[^\r\n?]*(?:\?(?!>)[^\r\n?]*)*")
_PHP_SINGLE_QUOTED = re.compile(r"(?:\\.|[^'\\])*'", re.DOTALL)
_PHP_INTERPOLATION = r"\\.|\{\$|\$\{"
MAX_PHP_FILES = 500

# Without a Python manifest, the imports are the only evidence of a framework or a database.
_PYTHON_MANIFESTS = {"pyproject.toml", "setup.py", "setup.cfg", "Pipfile"}
_PYTHON_IMPORTS = {
    "sqlite3": ("SQLite", "data"), "pymysql": ("MySQL", "data"), "MySQLdb": ("MySQL", "data"),
    "mysql": ("MySQL", "data"),  # mysql.connector
    **{module: NOTABLE[module] for module in (
        "django", "flask", "fastapi", "typer", "click", "sqlalchemy", "alembic", "psycopg",
        "psycopg2", "asyncpg", "pymongo", "redis", "celery",
    )},
}
MAX_PYTHON_FILES = 500


# Without package.json, the imports read by the syntax graph are the evidence (tree-sitter:
# strings, comments and templates cannot fake one).
_JS_LANGUAGES = {"javascript", "typescript", "tsx"}
_JS_IMPORTS = {
    **{package: NOTABLE[package] for package in (
        "react", "vue", "svelte", "next", "nuxt", "@sveltejs/kit", "@angular/core", "express",
        "fastify", "@nestjs/core", "hono", "prisma", "@prisma/client", "drizzle-orm", "typeorm",
        "mongoose", "pg", "mysql2", "ioredis", "graphql", "@trpc/server",
    )},
    "mysql": ("MySQL", "data"), "sqlite3": ("SQLite", "data"),
    "better-sqlite3": ("SQLite", "data"), "mongodb": ("MongoDB", "data"),
    "redis": ("Redis", "data"), "koa": ("Koa", "framework"),
}

CATEGORIES = [
    "language", "framework", "ui", "data", "api", "ai", "infra", "ci", "testing", "tooling",
    "library",
]
_VENDORED = {"node_modules", "vendor", "third_party"}
_SELF_DECLARING = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod"}
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_REQUIREMENTS_FILE = re.compile(r"^requirements.*\.txt$")
_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([a-z0-9.-]+\.[a-z]{2,}/\S+)\s+v\S+", re.MULTILINE)
_COMPOSE_FILE = re.compile(r"^(docker-)?compose(\.[\w-]+)?\.ya?ml$")
_IMAGE = re.compile(r"^\s*image:\s*[\"']?([\w./-]+)", re.MULTILINE)
MAX_MANIFEST_BYTES = 2_000_000
_GRADLE_COORDINATE = re.compile(
    r"[\"']([\w.-]+:[\w.-]+)(?::[^\"']*)?[\"']"
)
_GRADLE_MAP = re.compile(
    r"group\s*[:=]\s*[\"']([\w.-]+)[\"']\s*,\s*name\s*[:=]\s*[\"']([\w.-]+)[\"']"
)
_GEM = re.compile(r"^\s*gem\s*(?:\(\s*)?[\"']([\w.-]+)[\"']", re.MULTILINE)
_PROVIDER = re.compile(r'\bsource\s*=\s*"([\w./-]+)"')
_LEGACY_PROVIDER = re.compile(r'\bprovider\s+"([\w-]+)"\s*\{')


def _php_databases(path: Path) -> list[tuple[str, str, str]]:
    """Databases a PHP file connects to, with the text that dates their adoption.

    A small lexer over PHP blocks: comments, strings, heredocs and nowdocs are skipped, and
    an interpolation (`{$…}`, `${…}`) is code again, so a heredoc nested in it, even with
    the outer label, closes before the outer one. Out of scope: short `<?` tags and
    connections built at runtime."""
    text = _read(path)
    found: list[tuple[str, str, str]] = []
    mysqli = None
    position = 0
    while opening := _PHP_OPEN.search(text, position):
        position = opening.end()
        # Innermost context last: ["code", unmatched braces], ["string", end pattern].
        stack: list[list] = [["code", 0]]
        while stack:
            top = stack[-1]
            if top[0] == "string":
                match = top[1].search(text, position)
                if match is None:
                    return _with_mysqli(found, mysqli)  # unterminated: the file ends here
                position = match.end()
                if match["end"] is not None:
                    stack.pop()
                elif match.group() in ("{$", "${"):
                    position -= 1 if match.group() == "{$" else 0  # `$` starts the code
                    stack.append(["code", 0])
                continue
            match = _PHP_CODE.search(text, position)
            if match is None:
                return _with_mysqli(found, mysqli)  # the last PHP block runs to the end
            position = match.end()
            if match["close"]:
                if len(stack) == 1:
                    break  # back to HTML until the next opening tag
            elif match["line"]:
                position = _PHP_LINE_COMMENT.match(text, position).end()
            elif match["block"]:
                close = text.find("*/", position)
                position = len(text) if close < 0 else close + 2
            elif match["string"] == "'":
                quoted = _PHP_SINGLE_QUOTED.match(text, position)
                position = len(text) if quoted is None else quoted.end()
            elif match["string"]:
                ending = re.escape(match["string"])
                stack.append(["string", re.compile(
                    rf"(?P<end>{ending})|{_PHP_INTERPOLATION}", re.DOTALL,
                )])
            elif match["label"]:
                label = re.escape(match["label"])
                closing = rf"(?P<end>(?<=[\r\n])[\ \t]*{label}(?![A-Za-z_0-9\x80-\U0010ffff]))"
                nowdoc = match["hq"] == "'"
                stack.append(["string", re.compile(
                    closing if nowdoc else rf"{closing}|{_PHP_INTERPOLATION}", re.DOTALL,
                )])
            elif match["open"]:
                top[1] += 1
            elif match["shut"]:
                if top[1]:
                    top[1] -= 1
                elif len(stack) > 1:
                    stack.pop()  # end of an interpolation: back into its string
            elif driver := match["driver"]:
                found.append((_PHP_DATABASES[driver], "data", f"{driver}:"))
            elif mysqli is None and match["mysqli"]:
                mysqli = match["mysqli"].rstrip()
        if not stack:
            break
    return _with_mysqli(found, mysqli)


def _with_mysqli(
    found: list[tuple[str, str, str]], mysqli: str | None,
) -> list[tuple[str, str, str]]:
    return [*found, ("MySQL", "data", mysqli)] if mysqli else found


def _python_imports(path: Path) -> list[tuple[str, str, str]]:
    """Known frameworks and databases a Python file imports, with the import line that dates
    them. `ast` reads real import statements only: strings and comments cannot fake one."""
    try:
        data = _read_bytes(path)
        header_lines = BytesIO(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))
        encoding, _ = tokenize.detect_encoding(header_lines.readline)
        text = data.decode(encoding)
        tree = ast.parse(text)
    except (SyntaxError, UnicodeError, LookupError, RecursionError, MemoryError):
        return []  # Python 2 or broken source: no evidence rather than a guess
    lines = re.split(r"\r\n|\r|\n", text)  # ast's line breaks; splitlines also cuts at \f
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            modules = [node.module]
        else:
            continue
        for module in modules:
            if known := _PYTHON_IMPORTS.get(module.split(".", 1)[0]):
                found.append((*known, lines[node.lineno - 1].strip()))
    return found


def _js_package(specifier: str) -> str:
    """`@scope/name/sub` → `@scope/name`, `express/lib/router` → `express`."""
    parts = specifier.split("/")
    return "/".join(parts[:2]) if specifier.startswith("@") else parts[0]


def with_imports(
    root: Path, files: list[str], technologies: list[Technology], graph: Any,
) -> list[Technology]:
    """Add the JS/TS frameworks and databases a project imports when it has no package.json,
    from the syntax graph (None without the code extra), dated by their import line."""
    if graph is None or any(
        PurePosixPath(path).name == "package.json" and not _priority(path)[0]
        for path in files
    ):
        return technologies
    found = {t.name: t for t in technologies}
    for path in sorted(graph.modules, key=_priority):
        module = graph.modules[path]
        if module.language not in _JS_LANGUAGES or _VENDORED & set(PurePosixPath(path).parts):
            continue
        lines = None
        for item in module.imports:
            known = _JS_IMPORTS.get(_js_package(item.module))
            if known is None or known[0] in found:
                continue
            if lines is None:
                try:
                    lines = _read(root / path).splitlines()
                except (OSError, ValueError):
                    break
            needle = lines[item.line - 1].strip() if 0 < item.line <= len(lines) else None
            found[known[0]] = Technology(
                name=known[0], category=known[1], source=path, needle=needle,
            )
    return sorted(found.values(), key=lambda t: (CATEGORIES.index(t.category), t.name.lower()))


def _read_bytes(path: Path) -> bytes:
    with path.open("rb") as file:
        data = file.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds size limit")
    return data


def _read(path: Path) -> str:
    return _read_bytes(path).decode("utf-8")


def _xml(path: Path) -> ET.Element:
    text = _read(path)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML entities are not permitted")
    return ET.fromstring(text)


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _maven_deps(path: Path) -> list[str]:
    names = []
    for element in _xml(path).iter():
        if _local_tag(element) not in {"dependency", "parent"}:
            continue
        fields = {_local_tag(child): (child.text or "").strip() for child in element}
        if fields.get("groupId") and fields.get("artifactId"):
            names.append(f"{fields['groupId']}:{fields['artifactId']}")
    return names


def _gradle_deps(path: Path) -> list[str]:
    # Only literal declarations. Never execute Groovy/Kotlin to resolve expressions/catalogs.
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", _read(path), flags=re.DOTALL)
    return [*_GRADLE_COORDINATE.findall(text), *(f"{a}:{b}" for a, b in _GRADLE_MAP.findall(text))]


def _ruby_deps(path: Path) -> list[str]:
    return _GEM.findall(_read(path))


def _php_deps(path: Path) -> list[str]:
    data = json.loads(_read(path))
    if not isinstance(data, dict):
        raise ValueError("composer.json must contain an object")
    return [
        name for key in ("require", "require-dev")
        for name in (data.get(key) or {}) if name != "php" and not name.startswith("ext-")
    ]


def _dotnet_deps(path: Path) -> list[str]:
    root = _xml(path)
    names = [root.attrib["Sdk"]] if "Sdk" in root.attrib else []
    for element in root.iter():
        if _local_tag(element) in {"PackageReference", "FrameworkReference"}:
            name = element.attrib.get("Include") or element.attrib.get("Update")
            if name:
                names.append(name)
    return names


def _python_deps(path: Path) -> list[str]:
    if path.name != "pyproject.toml":  # requirements*.txt
        lines = _read(path).splitlines()
        specs = [line for line in lines if not line.lstrip().startswith(("#", "-"))]
        names = []
    else:
        data = tomllib.loads(_read(path))
        project = data.get("project", {})
        specs = list(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            specs += group
        for group in data.get("dependency-groups", {}).values():
            specs += [spec for spec in group if isinstance(spec, str)]
        poetry = data.get("tool", {}).get("poetry", {})
        names = [*poetry.get("dependencies", {})]
        for group in poetry.get("group", {}).values():
            names += [*group.get("dependencies", {})]
    names += [m[1] for spec in specs if (m := _REQUIREMENT.match(spec))]
    return [name for name in names if name.lower() != "python"]


def _node_deps(path: Path) -> list[str]:
    data = json.loads(_read(path))
    if not isinstance(data, dict):
        raise ValueError("package.json must contain an object")
    keys = ("dependencies", "devDependencies", "peerDependencies")
    if any(key in data and not isinstance(data[key], dict) for key in keys):
        raise ValueError("package dependencies must be objects")
    return [name for key in keys for name in data.get(key, {})]


def _go_deps(path: Path) -> list[str]:
    return _GO_REQUIRE.findall(_read(path))


def _cargo_deps(path: Path) -> list[str]:
    data = tomllib.loads(_read(path))
    workspace = data.get("workspace", {}).get("dependencies", {})
    return [*data.get("dependencies", {}), *data.get("dev-dependencies", {}), *workspace]


MANIFESTS: dict[str, Callable[[Path], list[str]]] = {
    "pyproject.toml": _python_deps,
    "package.json": _node_deps,
    "go.mod": _go_deps,
    "Cargo.toml": _cargo_deps,
    "pom.xml": _maven_deps,
    "build.gradle": _gradle_deps,
    "build.gradle.kts": _gradle_deps,
    "Gemfile": _ruby_deps,
    "composer.json": _php_deps,
}


def _priority(path: str) -> tuple[bool, int, bool, str]:
    """Main manifests first: the root, then shallower paths, auxiliary folders last. In a
    folder, index.php comes first: a plain PHP project's entry point, usually its oldest file."""
    parts = PurePosixPath(path).parts
    return is_auxiliary_source(path), len(parts), parts[-1] != "index.php", path


def _key(parser: Callable[[Path], list[str]], name: str) -> tuple[Callable, str]:
    # PEP 503 equivalence belongs to Python, not to npm or Go module names.
    normalized = re.sub(r"[-_.]+", "-", name.lower()) if parser is _python_deps else name
    return parser, normalized


def _declared_name(path: Path) -> str | None:
    """The package a manifest declares, so that the repository's own packages (the project
    itself, its examples, the members of a monorepo) are not reported as technologies."""
    name = None
    if path.name == "pyproject.toml":
        data = tomllib.loads(_read(path))
        name = data.get("project", {}).get("name") or (
            data.get("tool", {}).get("poetry", {}).get("name")
        )
    elif path.name == "package.json":
        data = json.loads(_read(path))
        name = data.get("name") if isinstance(data, dict) else None
    elif path.name == "Cargo.toml":
        name = tomllib.loads(_read(path)).get("package", {}).get("name")
    elif path.name == "go.mod":
        match = re.search(r"^module\s+(\S+)", _read(path), re.MULTILINE)
        name = match[1] if match else None
    return name if isinstance(name, str) else None


def _lookup(dependency: str) -> tuple[str, str]:
    name = dependency.lower()
    if name.startswith("org.springframework.boot:spring-boot-"):
        return "Spring Boot", "framework"
    if name.startswith("io.ktor:ktor-"):
        return "Ktor", "framework"
    pep503 = re.sub(r"[-_.]+", "-", name)
    return NOTABLE.get(name) or NOTABLE.get(pep503) or (dependency, "library")


def _infra(path: Path) -> list[tuple[str, str, str | None]]:
    if path.suffix == ".tf":
        text = re.sub(r"#[^\n]*|//[^\n]*|/\*.*?\*/", "", _read(path), flags=re.DOTALL)
        providers = []
        for match in re.finditer(r"\brequired_providers\s*\{", text):
            depth, end = 1, match.end()
            while end < len(text) and depth:
                depth += (text[end] == "{") - (text[end] == "}")
                end += 1
            if depth == 0:
                providers.extend(_PROVIDER.findall(text[match.end():end - 1]))
        providers += [p for p in _LEGACY_PROVIDER.findall(text) if not any(
            source.rsplit("/", 1)[-1] == p for source in providers
        )]
        return [(f"Terraform provider: {provider}", "infra", provider) for provider in providers]
    if path.suffix not in {".yaml", ".yml"}:
        return []
    signals = []
    for document in yaml.safe_load_all(_read(path)):
        if not isinstance(document, dict):
            continue
        if (
            isinstance(document.get("apiVersion"), str)
            and isinstance(document.get("kind"), str)
            and isinstance(document.get("metadata"), dict)
        ):
            signals.append(("Kubernetes", "infra", "apiVersion"))
        if path.name == "Chart.yaml":
            for dependency in document.get("dependencies", []) or []:
                name = dependency.get("name") if isinstance(dependency, dict) else None
                if isinstance(name, str):
                    found = IMAGES.get(name)
                    signals.append(
                        (*found, name) if found else (f"Helm chart: {name}", "infra", name)
                    )
    return signals


def detect(root: Path, files: list[str]) -> list[Technology]:
    """Technologies found in the project's manifests, compose files and config files."""
    found: dict[str, Technology] = {}

    def add(name: str, category: str, source: str, needle: str | None = None) -> None:
        if name not in found:  # first source wins
            # Main sources are read first, so an auxiliary first source means no main one.
            found[name] = Technology(
                name=name, category=category, source=source, needle=needle,
            )

    # The root manifest must win over an example or a test fixture declaring the same package.
    ordered = [
        f for f in sorted(files, key=_priority) if not _VENDORED & set(PurePosixPath(f).parts)
    ]
    # Choose a manifest before falling back to source files in the same scope.
    php_source = min(
        (f for f in ordered if PurePosixPath(f).name == "composer.json" or f.endswith(".php")),
        key=lambda f: (is_auxiliary_source(f), PurePosixPath(f).name != "composer.json"),
        default=None,
    )
    own = set()
    auxiliary_own = set()
    python_manifest = any(
        not _priority(f)[0] and (
            PurePosixPath(f).name in _PYTHON_MANIFESTS
            or _REQUIREMENTS_FILE.match(PurePosixPath(f).name)
        )
        for f in ordered
    )
    python_files = 0
    php_files = 0
    for path in ordered:
        if PurePosixPath(path).name in _SELF_DECLARING:
            try:
                declared = _declared_name(root / path)
            except (OSError, ValueError, TypeError, AttributeError):
                declared = None
            if declared:
                names = auxiliary_own if _priority(path)[0] else own
                names.add(_key(MANIFESTS[PurePosixPath(path).name], declared))

    for path in ordered:
        p = PurePosixPath(path)
        parser = MANIFESTS.get(p.name) or (
            _python_deps if _REQUIREMENTS_FILE.match(p.name) else None
        )
        if p.suffix == ".csproj":
            parser = _dotnet_deps
        if parser:
            try:
                dependencies = parser(root / path)
            except (OSError, ValueError, TypeError, AttributeError, ET.ParseError):
                dependencies = []
            for dep in dependencies:
                if not isinstance(dep, str):
                    continue
                key = _key(parser, dep)
                if key in own or (_priority(path)[0] and key in auxiliary_own):
                    continue
                name, category = _lookup(dep)
                needle = f'"{dep}"' if p.name == "package.json" else dep
                if p.name == "pom.xml":
                    needle = dep.rsplit(":", 1)[-1]
                add(name, category, path, needle)

        try:
            for name, category, needle in _infra(root / path):
                add(name, category, path, needle)
        except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError, RecursionError):
            pass  # invalid/templated YAML and unreadable manifests are not executable

        if _COMPOSE_FILE.match(p.name):
            add("Docker Compose", "infra", path)
            try:
                images = _IMAGE.findall(_read(root / path))
            except (OSError, ValueError):
                images = []
            for image in images:
                base = image.rsplit("/", 1)[-1].split(":")[0]
                if base in IMAGES:
                    add(*IMAGES[base], path, base)

        if p.suffix == ".php" and php_files < MAX_PHP_FILES:
            php_files += 1
            try:
                for name, category, needle in _php_databases(root / path):
                    add(name, category, path, needle)
            except (OSError, ValueError):
                pass  # oversized or non-UTF-8 source: no evidence rather than a guess

        if p.suffix == ".py" and not python_manifest and python_files < MAX_PYTHON_FILES:
            python_files += 1
            try:
                for name, category, needle in _python_imports(root / path):
                    add(name, category, path, needle)
            except (OSError, ValueError):
                pass  # oversized or non-UTF-8 source

        if path == php_source:
            add("PHP", "language", path)

        for pattern, (name, category) in FILE_SIGNALS.items():
            if fnmatch(path if "/" in pattern else p.name, pattern):
                add(name, category, path)

    return sorted(found.values(), key=lambda t: (CATEGORIES.index(t.category), t.name.lower()))
