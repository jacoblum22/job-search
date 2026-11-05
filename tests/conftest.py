import pytest

from src.tailor import paths


@pytest.fixture(autouse=True)
def _tailor_state_in_tmp(tmp_path, monkeypatch):
    """Keep every test out of the real materials/ folder.

    A test that leans on a default path otherwise reads Jake's own files when they're
    there (vault passage titles instead of ids) and passes only on a fresh clone.
    """
    for name, default in list(paths.DEFAULT_PATHS.items()):
        if default.startswith("materials"):
            monkeypatch.setitem(paths.DEFAULT_PATHS, name, str(tmp_path / "materials-defaults" / default))
    monkeypatch.setitem(paths.DEFAULT_PATHS, "skill_record", str(tmp_path / "state" / "skill-record.json"))
    monkeypatch.setitem(paths.DEFAULT_PATHS, "jev_cache", str(tmp_path / "state" / "jev-cache.json"))
    # The real .env may say JOBSEARCH_DB=postgres (after the phase 4 cutover); tests never use it.
    monkeypatch.setenv("JOBSEARCH_DB", "sqlite")
