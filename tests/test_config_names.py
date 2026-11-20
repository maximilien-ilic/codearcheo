"""Settings keep working under the names from before the rename to codearcheo."""

from codearcheo.config import Settings, cache_dir_from_env


def test_new_names_win_over_the_ones_from_before_the_rename(monkeypatch, tmp_path):
    monkeypatch.setenv("LEARN_IT_EFFORT", "high")
    assert Settings.from_env().effort == "high"
    monkeypatch.setenv("CODEARCHEO_EFFORT", "low")
    assert Settings.from_env().effort == "low"


def test_the_backend_and_cache_from_before_the_rename_are_still_read(monkeypatch, tmp_path):
    monkeypatch.setenv("LEARN_IT_BACKEND", "claude-code")
    monkeypatch.setenv("LEARN_IT_CACHE_DIR", str(tmp_path))
    assert Settings.from_env().backend == "claude-code"
    assert cache_dir_from_env() == tmp_path
