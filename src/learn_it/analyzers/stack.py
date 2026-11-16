"""Detect the tech stack from manifests and config files. Deterministic: no LLM involved."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from learn_it.domain import Technology

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
}

CATEGORIES = [
    "language", "framework", "ui", "data", "api", "ai", "infra", "ci", "testing", "tooling",
    "library",
]
_VENDORED = {"node_modules", "vendor", "third_party"}
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_REQUIREMENTS_FILE = re.compile(r"^requirements.*\.txt$")
_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([a-z0-9.-]+\.[a-z]{2,}/\S+)\s+v\S+", re.MULTILINE)
_COMPOSE_FILE = re.compile(r"^(docker-)?compose(\.[\w-]+)?\.ya?ml$")
_IMAGE = re.compile(r"^\s*image:\s*[\"']?([\w./-]+)", re.MULTILINE)


def _python_deps(path: Path) -> list[str]:
    if path.name != "pyproject.toml":  # requirements*.txt
        lines = path.read_text().splitlines()
        specs = [line for line in lines if not line.lstrip().startswith(("#", "-"))]
        names = []
    else:
        data = tomllib.loads(path.read_text())
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
    data = json.loads(path.read_text())
    keys = ("dependencies", "devDependencies", "peerDependencies")
    return [name for key in keys for name in data.get(key, {})]


def _go_deps(path: Path) -> list[str]:
    return _GO_REQUIRE.findall(path.read_text())


def _cargo_deps(path: Path) -> list[str]:
    data = tomllib.loads(path.read_text())
    workspace = data.get("workspace", {}).get("dependencies", {})
    return [*data.get("dependencies", {}), *data.get("dev-dependencies", {}), *workspace]


MANIFESTS: dict[str, Callable[[Path], list[str]]] = {
    "pyproject.toml": _python_deps,
    "package.json": _node_deps,
    "go.mod": _go_deps,
    "Cargo.toml": _cargo_deps,
}


def _lookup(dependency: str) -> tuple[str, str]:
    name = dependency.lower()
    pep503 = re.sub(r"[-_.]+", "-", name)
    return NOTABLE.get(name) or NOTABLE.get(pep503) or (dependency, "library")


def detect(root: Path, files: list[str]) -> list[Technology]:
    """Technologies found in the project's manifests, compose files and config files."""
    found: dict[str, Technology] = {}

    def add(name: str, category: str, source: str, needle: str | None = None) -> None:
        if name not in found:  # first source wins
            found[name] = Technology(name=name, category=category, source=source, needle=needle)

    for path in files:
        p = PurePosixPath(path)
        if _VENDORED & set(p.parts):
            continue

        parser = MANIFESTS.get(p.name) or (
            _python_deps if _REQUIREMENTS_FILE.match(p.name) else None
        )
        if parser:
            try:
                dependencies = parser(root / path)
            except (OSError, ValueError):  # unreadable or malformed manifest
                dependencies = []
            for dep in dependencies:
                name, category = _lookup(dep)
                add(name, category, path, f'"{dep}"' if p.name == "package.json" else dep)

        if _COMPOSE_FILE.match(p.name):
            add("Docker Compose", "infra", path)
            for image in _IMAGE.findall((root / path).read_text(errors="replace")):
                base = image.rsplit("/", 1)[-1].split(":")[0]
                if base in IMAGES:
                    add(*IMAGES[base], path, base)

        for pattern, (name, category) in FILE_SIGNALS.items():
            if fnmatch(path if "/" in pattern else p.name, pattern):
                add(name, category, path)

    return sorted(found.values(), key=lambda t: (CATEGORIES.index(t.category), t.name.lower()))
