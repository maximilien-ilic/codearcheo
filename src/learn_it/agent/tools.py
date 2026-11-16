"""Read-only tools an agent explores a project with.

The same methods back the internal agent (through the Anthropic tool runner) and the MCP
server, so every agent sees the project the same way. Each returns plain text and raises
ToolError with an actionable message when a call cannot be served. Their docstrings are the
tool descriptions the model reads.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path

from anthropic.lib.tools import ToolError

from learn_it import git
from learn_it.analyzers import inventory
from learn_it.domain import ProjectProfile

MAX_CHARS = 20_000  # per result: enough to be useful, small enough to keep the context lean
MAX_FILES = 500
MAX_MATCHES = 200
MAX_LINE = 300
READ_WINDOW = 400
_SHA = re.compile(r"^[0-9a-fA-F]{4,40}$")
# Keep likely secrets out of diffs too.
_NO_SECRETS = [f":(exclude,glob)**/{pattern}" for pattern in inventory.SECRET_PATTERNS]


def _clip(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + f"\n… [{len(text) - MAX_CHARS} more characters: narrow the request]"


class ProjectTools:
    def __init__(self, root: Path, profile: ProjectProfile) -> None:
        self.root = root.resolve()
        self.profile = profile
        self.is_git = git.is_repo(self.root)

    def exploration(self) -> list[Callable[..., str]]:
        """Tools to explore code and history; the git ones only exist in a git repository."""
        tools = [self.list_files, self.search_code, self.read_file]
        if self.is_git:
            tools += [self.git_log, self.git_show, self.git_blame]
        return tools

    def _git(self, *args: str, ok: tuple[int, ...] = (0,)) -> str:
        try:
            return git.run(self.root, *args, ok=ok)
        except git.GitError as exc:
            raise ToolError(f"git: {exc}") from exc

    def _safe_path(self, path: str) -> str:
        """Normalize a project-relative path, refusing what lies outside the project, in .git,
        ignored by git or likely to hold secrets."""
        # Inspect the original spelling before resolve() erases symlinks.
        if not inventory.is_safe_path(self.root, path):
            raise ToolError(f"{path} is off limits: symlink, git internals or likely secrets.")
        full = (self.root / path).resolve()
        if not full.is_relative_to(self.root):
            raise ToolError(f"{path} is outside the project.")
        rel = full.relative_to(self.root).as_posix()
        if rel == ".git" or rel.startswith(".git/") or inventory.is_secret(rel):
            raise ToolError(f"{path} is off limits: git internals or likely secrets.")
        # check-ignore prints the path when git ignores it; tracked files never count as ignored
        if self.is_git and rel != "." and self._git("check-ignore", "--", rel, ok=(0, 1)).strip():
            raise ToolError(f"{path} is ignored by git, so learn-it does not read it.")
        return rel

    def project_profile(self) -> str:
        """The project's deterministic profile computed by `learn-it scan`: languages, stack with
        the commit that adopted each technology, activity, hotspots, docs and uncommitted work.
        Start here."""
        return self.profile.model_dump_json(indent=1)

    def list_files(self, pattern: str = "*") -> str:
        """List the project's files, gitignored ones excluded, whose path matches a glob.

        Args:
            pattern: Glob on the path relative to the project root; `*` also matches `/`.
                Examples: "*.py", "src/api/*", "*test*".
        """
        matches = [f for f in inventory.list_files(self.root) if fnmatch(f, pattern)]
        if not matches:
            return f"No file matches {pattern!r}."
        more = len(matches) - MAX_FILES
        footer = f"\n… and {more} more: narrow the pattern." if more > 0 else ""
        return _clip("\n".join(matches[:MAX_FILES]) + footer)

    def search_code(self, regex: str, pattern: str = "") -> str:
        """Search file contents with an extended regular expression, like `grep -rn`.

        Returns matching lines as `path:line:text`. Search first, then read only what matters.

        Args:
            regex: Extended regular expression, e.g. "class \\w+Repository" or "redis|memcached".
            pattern: Optional glob restricting the searched files, e.g. "*.py" or "src/*".
        """
        if self.is_git:
            pathspec = [pattern] if pattern else []
            out = self._git(
                "grep", "-n", "-I", "-E", "--untracked", "-e", regex, "--", *pathspec, ok=(0, 1)
            )
            lines = out.splitlines()
        else:
            lines = self._grep_without_git(regex, pattern)
        lines = [
            line[:MAX_LINE]
            for line in lines
            if inventory.is_safe_path(self.root, line.split(":", 1)[0])
        ]
        if not lines:
            return "No matches."
        more = len(lines) - MAX_MATCHES
        footer = f"\n… {more} more matches: refine the regex or the pattern." if more > 0 else ""
        return _clip("\n".join(lines[:MAX_MATCHES]) + footer)

    def _grep_without_git(self, regex: str, pattern: str) -> list[str]:
        try:
            compiled = re.compile(regex)
        except re.error as exc:
            raise ToolError(f"Invalid regex: {exc}") from exc
        lines: list[str] = []
        for rel in inventory.list_files(self.root):
            if pattern and not fnmatch(rel, pattern):
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):  # binary or unreadable
                continue
            numbered = enumerate(text.splitlines(), 1)
            lines += [f"{rel}:{n}:{line}" for n, line in numbered if compiled.search(line)]
            if len(lines) > MAX_MATCHES:
                break
        return lines

    def read_file(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        """Read a text file with line numbers, at most 400 lines per call.

        Args:
            path: File path relative to the project root.
            start_line: First line to return, 1-based.
            end_line: Last line to return, inclusive. 0 means start_line + 399.
        """
        rel = self._safe_path(path)
        full = self.root / rel
        if not full.is_file():
            raise ToolError(f"No such file: {path}. Use list_files to find the right path.")
        if full.stat().st_size > 5_000_000:
            raise ToolError(f"{path} is too large to read; use search_code on it instead.")
        data = full.read_bytes()
        if b"\0" in data[:8192]:
            raise ToolError(f"{path} is a binary file.")
        lines = data.decode("utf-8", errors="replace").splitlines()
        start = max(start_line, 1)
        if start > len(lines):
            raise ToolError(f"{path} has only {len(lines)} lines.")
        last = start + READ_WINDOW - 1
        end = min(end_line, last) if end_line >= start else last
        end = min(end, len(lines))
        body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))
        rest = len(lines) - end
        footer = f"\n… {rest} more lines: call again with start_line={end + 1}." if rest > 0 else ""
        return _clip(f"{rel}, lines {start}-{end} of {len(lines)}\n{body}{footer}")

    def git_log(self, path: str = "", grep: str = "", limit: int = 20) -> str:
        """Commit history, newest first: short sha, date, author, subject and changed files.

        Args:
            path: Only commits touching this file or directory, deleted ones included.
                Empty for the whole project.
            grep: Only commits whose message matches this regex, case-insensitive,
                e.g. "migrat|replace|switch to".
            limit: Maximum number of commits, at most 100.
        """
        args = ["log", f"-n{max(1, min(limit, 100))}", "--date=short", "--relative",
                "--format=%n%h %ad %an%n    %s", "--name-status"]
        if grep:
            args += ["-i", "-E", f"--grep={grep}"]
        args += ["--", *([self._safe_path(path)] if path else [])]
        out = self._git(*args).strip()
        return _clip(out) if out else "No matching commits."

    def git_show(self, commit: str, patch: bool = False) -> str:
        """One commit in full: message, author, dates and changed files, optionally the diff.

        Args:
            commit: Commit sha, at least 4 hexadecimal characters.
            patch: Include the diff, to see exactly what the commit introduced.
        """
        if not _SHA.match(commit):
            raise ToolError("commit must be a hexadecimal sha.")
        args = ["show", "--format=fuller", "--stat", "--relative"]
        if patch:
            args += ["-p", commit, "--", ".", *_NO_SECRETS]
        else:
            args += [commit, "--"]
        return _clip(self._git(*args))

    def git_blame(self, path: str, start_line: int, end_line: int) -> str:
        """Who last changed each line, when, and in which commit: the way into "why is this
        line here?". Follow up with git_show on the shas that matter.

        Args:
            path: File path relative to the project root.
            start_line: First line, 1-based.
            end_line: Last line, inclusive. Ranges are capped at 200 lines.
        """
        rel = self._safe_path(path)
        end = min(max(end_line, start_line), start_line + 199)
        lines = f"-L{start_line},{end}"
        return _clip(self._git("blame", "-w", "-M", "--date=short", lines, "--", rel))
