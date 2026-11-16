import json
import runpy
from pathlib import Path

import pytest

gate = runpy.run_path(str(Path(__file__).parents[1] / "scripts/review_gate.py"))


def test_duplicate_commits_and_foreign_statuses():
    pending = gate["pending"]
    assert pending({}, {"sha": "a"}, 100)
    assert not pending({"completed_sha": "a"}, {"sha": "a"}, 100)
    assert pending({"completed_sha": "a"}, {"sha": "b"}, 100)
    snapshot = {"sha": "a", "statuses": [{"context": "ci", "state": "success"}]}
    assert pending({}, snapshot, 100)
    snapshot["statuses"][0]["context"] = "codex/review"
    assert not pending({}, snapshot, 100)


def test_lease_prevents_parallel_reviews_even_when_head_changes():
    state = {"completed_sha": "old"}
    first = gate["claim"](state, {"sha": "a"}, 100)
    assert first["baseline"] == "old"
    assert gate["claim"](state, {"sha": "b"}, 101) is None
    retry = gate["claim"](state, {"sha": "b"}, 100 + gate["LEASE_SECONDS"])
    assert retry["token"] != first["token"]
    assert retry["baseline"] == "old"
    with pytest.raises(ValueError):
        gate["finish"](state, first["token"], success=True)


def test_complete_marks_only_the_claimed_sha_and_keeps_new_push_pending(monkeypatch):
    calls = []
    monkeypatch.setitem(gate["finish"].__globals__, "gh", lambda *args: calls.append(args))
    state = {}
    lease = gate["claim"](state, {"sha": "a"}, 100)
    assert gate["finish"](state, lease["token"], success=True) == "a"
    assert state == {"completed_sha": "a"}
    assert calls[0][0].endswith("/statuses/a")
    assert gate["pending"](state, {"sha": "b"}, 101)


def test_failure_retries_without_advancing_checkpoint():
    state = {"completed_sha": "old"}
    lease = gate["claim"](state, {"sha": "a"}, 100)
    gate["finish"](state, lease["token"], success=False)
    assert state == {"completed_sha": "old"}
    assert gate["pending"](state, {"sha": "a"}, 101)


def test_api_failure_preserves_lease_and_checkpoint(monkeypatch):
    def unavailable(*args):
        raise OSError("API unavailable")

    monkeypatch.setitem(gate["finish"].__globals__, "gh", unavailable)
    state = {"completed_sha": "old"}
    lease = gate["claim"](state, {"sha": "a"}, 100)
    with pytest.raises(OSError):
        gate["finish"](state, lease["token"], success=True)
    assert state["completed_sha"] == "old"
    assert state["lease"] == lease


def test_checkpoint_is_persistent_and_is_not_written_on_error(tmp_path):
    with gate["locked_state"](tmp_path) as state:
        state["completed_sha"] = "old"
    with pytest.raises(RuntimeError), gate["locked_state"](tmp_path) as state:
        state["completed_sha"] = "incomplete"
        raise RuntimeError("interrupted")
    assert json.loads((tmp_path / "state.json").read_text()) == {"completed_sha": "old"}
