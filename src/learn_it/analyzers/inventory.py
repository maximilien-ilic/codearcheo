"""Inventory: which files the project has, in which languages, and where its docs are."""

from __future__ import annotations

import os
import re
from collections import Counter
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from learn_it import git

# Never listed, read or searched, even when tracked: such files tend to hold credentials.
SECRET_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa*", "id_ed25519*", ".netrc", ".npmrc", ".pypirc",
)
SECRET_EXCEPTIONS = (".env.example", ".env.sample", ".env.template", ".env.dist")

# Outside git there is no .gitignore to trust: skip the usual dependency and build directories.
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".learn-it", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "target", ".idea", ".vscode",
}

LANGUAGES = {
    ".py": "Python", ".ipynb": "Jupyter",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".vue": "Vue", ".svelte": "Svelte",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift", ".dart": "Dart",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".clj": "Clojure",
    ".lua": "Lua", ".r": "R", ".jl": "Julia", ".zig": "Zig",
    ".sql": "SQL", ".sh": "Shell", ".bash": "Shell", ".tf": "Terraform",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
}

_DOC_NAME = re.compile(
    r"^(readme|changelog|contributing|architecture|design|decisions?|history)([.-].*)?$",
    re.IGNORECASE,
)
_DOC_DIR = re.compile(r"(^|/)(docs?|adrs?|decisions|rfcs?)/", re.IGNORECASE)
_DOC_SUFFIXES = {".md", ".mdx", ".rst", ".adoc", ".txt", ""}


def is_secret(path: str) -> bool:
    return any(
        name not in SECRET_EXCEPTIONS and any(fnmatch(name, p) for p in SECRET_PATTERNS)
        for name in PurePosixPath(path).parts
    )


def is_safe_path(root: Path, path: str) -> bool:
    """Reject secrets, git internals and symlinks, including symlinked parent directories.

    Keep this policy shared by the inventory, manifest scan and exploration tools.
    """
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    if ".git" in relative.parts or is_secret(path):
        return False
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return False
    return True


def list_files(root: Path) -> list[str]:
    """Project files relative to `root`: tracked ones plus untracked but not ignored ones,
    because a project in progress has uncommitted work too."""
    if git.is_repo(root):
        out = git.run(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        paths = {p for p in out.split("\0") if p}
    else:
        paths = set()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel = Path(dirpath).relative_to(root)
            paths.update((rel / name).as_posix() for name in filenames)
    # is_file() drops deleted-but-staged entries and submodules
    return sorted(p for p in paths if is_safe_path(root, p) and (root / p).is_file())


def count_languages(files: list[str]) -> dict[str, int]:
    suffixes = (PurePosixPath(f).suffix.lower() for f in files)
    counts = Counter(LANGUAGES[s] for s in suffixes if s in LANGUAGES)
    return dict(counts.most_common())


def find_docs(files: list[str], limit: int = 40) -> list[str]:
    """Files likely to explain the project or its decisions, shallowest first."""

    def is_doc(path: str) -> bool:
        p = PurePosixPath(path)
        suffix = p.suffix.lower()
        if suffix not in _DOC_SUFFIXES:
            return False
        # files without extension only count by name (README, CHANGELOG), not by folder
        return bool(_DOC_NAME.match(p.name) or (suffix and _DOC_DIR.search(path)))

    return sorted((f for f in files if is_doc(f)), key=lambda f: (f.count("/"), f))[:limit]
