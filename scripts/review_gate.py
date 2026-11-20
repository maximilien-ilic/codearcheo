"""Local Orca review gate. Uses gh auth; never reads an API key or the target's code."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO = "maximilien-ilic/codearcheo"
BRANCH = "master"
CONTEXT = "codex/review"
LEASE_SECONDS = 2 * 60 * 60


def gh(*args: str) -> dict:
    result = subprocess.run(
        ["gh", "api", *args], check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(result.stdout)


def pending(state: dict, snapshot: dict, now: float) -> bool:
    lease = state.get("lease")
    if lease and now - lease["started_at"] < LEASE_SECONDS:
        return False
    if state.get("completed_sha") == snapshot["sha"]:
        return False
    return not any(
        status["context"] == CONTEXT and status["state"] == "success"
        for status in snapshot.get("statuses", [])
    )


@contextmanager
def locked_state(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        file = directory / "state.json"
        state = json.loads(file.read_text()) if file.exists() else {}
        yield state
        # Replace atomically so interruption cannot leave a truncated checkpoint.
        temp = directory / "state.json.tmp"
        temp.write_text(json.dumps(state, indent=2) + "\n")
        temp.chmod(0o600)
        temp.replace(file)


def claim(state: dict, snapshot: dict, now: float) -> dict | None:
    if not pending(state, snapshot, now):
        return None
    lease = {
        "sha": snapshot["sha"],
        "baseline": state.get("completed_sha"),
        "started_at": now,
        "token": uuid.uuid4().hex,
    }
    state["lease"] = lease
    return lease


def finish(state: dict, token: str, *, success: bool) -> str:
    lease = state.get("lease")
    if not lease or lease["token"] != token:
        raise ValueError("Review lease is missing or belongs to another run.")
    sha = lease["sha"]
    if success:
        # A success means reviewed, even when fixes await merging. Publish before checkpointing.
        gh(
            f"repos/{REPO}/statuses/{sha}", "-f", "state=success", "-f", f"context={CONTEXT}",
            "-f", "description=Revue effectuée ; conclusions dans les PR et tickets.",
            "-f", f"target_url=https://github.com/{REPO}/issues/4",
        )
        state["completed_sha"] = sha
    state.pop("lease", None)
    return sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "claim", "complete", "fail"))
    parser.add_argument("--token")
    state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    parser.add_argument("--state-dir", type=Path, default=state_root / "learn-it-review")
    args = parser.parse_args()
    if args.command in {"complete", "fail"} and not args.token:
        parser.error("--token is required to finish a review")

    try:
        with locked_state(args.state_dir) as state:
            if args.command in {"complete", "fail"}:
                print(finish(state, args.token, success=args.command == "complete"))
                return 0
            snapshot = gh(f"repos/{REPO}/commits/{BRANCH}/status")
            if args.command == "check":
                return 0 if pending(state, snapshot, time.time()) else 1
            lease = claim(state, snapshot, time.time())
            if lease is None:
                return 1
            print(json.dumps(lease))
            return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # Fail closed: an API/auth/state error must never be interpreted as new work.
        parser.exit(2, f"Review gate failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
