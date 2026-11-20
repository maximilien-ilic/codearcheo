"""Validate release artifacts and optionally smoke-test their isolated installation."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from datetime import date
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def source_version(root: Path) -> str:
    tree = ast.parse((root / "src/codearcheo/__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError("Version __version__ absente du module.")


def check_dist(root: Path, directory: Path, *, tag: str | None = None) -> list[Path]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    name, version = project["name"], project["version"]
    if not SEMVER.fullmatch(version) or source_version(root) != version:
        raise ValueError("Les versions du projet et du module doivent être identiques (X.Y.Z).")
    if tag:
        if tag != f"v{version}":
            raise ValueError(f"Le tag {tag!r} ne correspond pas à la version {version}.")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        entry = re.search(rf"^## \[{re.escape(version)}\] - (\d{{4}}-\d{{2}}-\d{{2}})$",
                          changelog, re.MULTILINE)
        if entry is None:
            raise ValueError(f"Aucune entrée datée pour {version} dans CHANGELOG.md.")
        date.fromisoformat(entry[1])
    wheels, sources = list(directory.glob("*.whl")), list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Le dossier doit contenir exactement un wheel et une archive source.")
    license_text = (root / "LICENSE").read_bytes()
    normalized = re.sub(r"[-_.]+", "_", name).lower()
    for artifact in [*wheels, *sources]:
        expected = f"{normalized}-{version}"
        if not (artifact.name.startswith(expected + "-") if artifact.suffix == ".whl"
                else artifact.name == expected + ".tar.gz"):
            raise ValueError(f"Nom d'archive incompatible avec la version : {artifact.name}")
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as wheel:
                metadata = [path for path in wheel.namelist()
                            if path.endswith(".dist-info/METADATA")]
                if len(metadata) != 1:
                    raise ValueError("METADATA absent ou multiple dans le wheel.")
                record = BytesParser().parsebytes(wheel.read(metadata[0]))
                license_path = metadata[0].removesuffix("METADATA") + "licenses/LICENSE"
                if license_path not in wheel.namelist() or wheel.read(license_path) != license_text:
                    raise ValueError("Licence absente ou différente dans le wheel.")
        else:
            with tarfile.open(artifact, "r:gz") as source:
                prefix = f"{normalized}-{version}"
                metadata_file = source.extractfile(f"{prefix}/PKG-INFO")
                license_file = source.extractfile(f"{prefix}/LICENSE")
                if metadata_file is None or license_file is None:
                    raise ValueError("Métadonnées ou licence absentes de l'archive source.")
                record = BytesParser().parsebytes(metadata_file.read())
                if license_file.read() != license_text:
                    raise ValueError("Licence différente dans l'archive source.")
        if record["Name"] != name or record["Version"] != version:
            raise ValueError(f"Métadonnées incohérentes dans {artifact.name}.")
        if record["License-Expression"] != project["license"]:
            raise ValueError(f"Licence incohérente dans les métadonnées de {artifact.name}.")
    return [*wheels, *sources]


def smoke_install(artifacts: list[Path], version: str) -> None:
    """Exercise the installed package away from the checkout; no generation command is run."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("CODEARCHEO_") and key not in {"PYTHONPATH", "PYTHONHOME"}}
    with tempfile.TemporaryDirectory(prefix="codearcheo-package-") as temporary:
        directory = Path(temporary)
        project = directory / "project"
        project.mkdir()
        (project / "app.py").write_text("def main(): return 1\n", encoding="utf-8")
        (project / "pyproject.toml").write_text(
            '[project]\nname = "package-smoke"\ndependencies = []\n', encoding="utf-8",
        )
        for artifact in artifacts:
            command = ["uv", "run", "--isolated", "--no-project", "--no-env-file",
                       "--with", str(artifact.resolve())]
            imported = subprocess.check_output(
                [*command, "python", "-I", "-c",
                 "import json, codearcheo; "
                 "print(json.dumps([codearcheo.__version__, codearcheo.__file__]))"],
                cwd=directory, env=env, text=True, timeout=300,
            )
            installed_version, location = json.loads(imported)
            if installed_version != version or Path(location).is_relative_to(ROOT):
                raise ValueError(f"L'installation de {artifact.name} utilise le mauvais module.")
            output = subprocess.check_output(
                [*command, "codearcheo", "scan", str(project), "--json"],
                cwd=directory, env=env, text=True, timeout=300,
            )
            profile = json.loads(output)
            if profile["name"] != "project" or "Python" not in profile["languages"]:
                raise ValueError(f"Le scan installé depuis {artifact.name} a échoué.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--tag", help="Stable release tag; also requires dated release notes.")
    parser.add_argument("--smoke", action="store_true", help="Install and scan from both packages.")
    options = parser.parse_args()
    try:
        artifacts = check_dist(ROOT, options.dist, tag=options.tag)
        if options.smoke:
            smoke_install(artifacts, source_version(ROOT))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError,
            subprocess.SubprocessError) as exc:
        print(f"Paquet invalide : {exc}", file=sys.stderr)
        return 1
    print("Paquets vérifiés : " + ", ".join(path.name for path in artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
