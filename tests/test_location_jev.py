from types import SimpleNamespace

from src import location_jev


class FakeClient:
    available = True

    def __init__(self, choice, conf=0.9, ok=True):
        self.choice, self.conf, self.ok, self.calls = choice, conf, ok, 0

    def ask(self, state, questions):
        self.calls += 1
        return [SimpleNamespace(ok=self.ok, value=self.choice, confidence=self.conf)]


def cfg(tmp_path):
    return {"jev_location": {"enabled": True, "cache": str(tmp_path / "c.json")}}


def test_verdict_is_used_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(location_jev, "ROOT", tmp_path)
    rows = [("Canada", "C# Developer ... company located in Raleigh, NC."), ("Toronto, ON", "x")]
    client = FakeClient("elsewhere")
    out = location_jev.verdicts(rows, cfg(tmp_path), client)
    assert out == {location_jev.key(rows[0][1]): "other"}
    location_jev.verdicts(rows, cfg(tmp_path), client)
    assert client.calls == 1   # second run reads the cache


def test_unclear_low_confidence_and_errors_leave_it_to_patterns(tmp_path, monkeypatch):
    monkeypatch.setattr(location_jev, "ROOT", tmp_path)
    rows = [("Canada", "some posting")]
    assert location_jev.verdicts(rows, cfg(tmp_path), FakeClient("unclear")) == {}
    (tmp_path / "c.json").unlink()
    assert location_jev.verdicts(rows, cfg(tmp_path), FakeClient("elsewhere", conf=0.4)) == {}
    (tmp_path / "c.json").unlink()
    assert location_jev.verdicts(rows, cfg(tmp_path), FakeClient(None, ok=False)) == {}


def test_off_by_default_and_remote_maps(tmp_path, monkeypatch):
    monkeypatch.setattr(location_jev, "ROOT", tmp_path)
    assert location_jev.verdicts([("Canada", "t")], {}, FakeClient("elsewhere")) == {}
    out = location_jev.verdicts([("Canada", "t")], cfg(tmp_path), FakeClient("remote_canada"))
    assert list(out.values()) == ["remote"]
