import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/claude-review.yml"


@pytest.mark.parametrize("has_reviewed_ancestor", [True, False])
def test_review_range_covers_skipped_push(project, tmp_path, has_reviewed_ancestor):
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Review test", "-c", "user.email=review@example.invalid",
             "-c", "commit.gpgsign=false", *args],
            cwd=project.root, text=True,
        ).strip()

    reviewed = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "push whose review was cancelled")
    git("commit", "--allow-empty", "-m", "latest push")
    sha = git("rev-parse", "HEAD")

    stub = tmp_path / "gh"
    stub.write_text(
        '#!/bin/sh\n'
        'if [ "$2" = "repos/example/project/commits/$REVIEWED/statuses" ]; then\n'
        '  echo success\n'
        'fi\n'
    )
    stub.chmod(0o755)
    output = tmp_path / "outputs"
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["review"]["steps"]
    script = next(step["run"] for step in steps if step.get("id") == "range")
    subprocess.run(
        ["bash", "-eo", "pipefail", "-c", script],
        cwd=project.root,
        env={
            "PATH": f"{tmp_path}{os.pathsep}{os.defpath}",
            "SHA": sha,
            "GITHUB_REPOSITORY": "example/project",
            "GITHUB_OUTPUT": str(output),
            "REVIEWED": reviewed if has_reviewed_ancestor else "",
        },
        check=True,
    )
    assert output.read_text() == f"base={reviewed if has_reviewed_ancestor else ''}\n"
