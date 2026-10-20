import pytest

from src.tailor import paths


@pytest.fixture(autouse=True)
def _tailor_state_in_tmp(tmp_path, monkeypatch):
    """Keep the shared reject and confirm lists and the Jev cache out of the real materials/ folder."""
    monkeypatch.setitem(paths.DEFAULT_PATHS, "skill_record", str(tmp_path / "state" / "skill-record.json"))
    monkeypatch.setitem(paths.DEFAULT_PATHS, "jev_cache", str(tmp_path / "state" / "jev-cache.json"))
