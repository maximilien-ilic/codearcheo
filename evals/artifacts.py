"""Identify the allowed source files used by a measurement, including uncommitted edits."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from codearcheo.analyzers import inventory


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(inventory.list_files(root)):
        content = hashlib.sha256()
        if not inventory.is_safe_path(root, path):
            raise OSError(f"Le projet a changé pendant son empreinte : {path}")
        with (root / path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                content.update(chunk)
        digest.update(path.encode("utf-8") + b"\0" + content.digest())
    return digest.hexdigest()


def save_report(output: Path, report: dict[str, Any]) -> None:
    """Checkpoint atomically with private permissions; each run owns a distinct filename."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}-", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
