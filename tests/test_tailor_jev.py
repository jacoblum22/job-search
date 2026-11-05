import json

import httpx
import pytest

from src.tailor import jev as jev_mod
from src.tailor.jev import Answer, JevClient, Question

YN = Question("sql", "yesno", "Does it mention SQL?")
SC = Question("level", "score", "How senior?", scale=(0, 3), criteria="0 intern .. 3 senior")
CH = Question("pick", "choice", "Which?", options=["a", "b"])

GOOD = {
    "model": "typesafe-ai/jev",
    "answers": {
        "sql": {"type": "boolean", "probability": 0.9},
        "level": {"type": "score", "score": 1.8, "probabilities": {"0": 0, "1": 0.2, "2": 0.8, "3": 0}, "confidence": 0.8},
        "pick": {"type": "choice", "choice": "b", "probabilities": {"a": 0.1, "b": 0.9}, "confidence": 0.7},
    },
    "usage": {"inputTokens": 120, "outputTokens": 5},
}


def make(handler, **cfg):
    sleeps: list[float] = []
    c = JevClient("k", cfg, transport=httpx.MockTransport(handler), sleep=sleeps.append)
    return c, sleeps


def test_no_key_makes_no_http_call():
    def boom(request):
        raise AssertionError("HTTP call without key")

    c = JevClient(None, transport=httpx.MockTransport(boom))
    out = c.ask("s", [YN, SC])
    assert not c.available
    assert [a.ok for a in out] == [False, False]
    assert [a.id for a in out] == ["sql", "level"]
    assert "AI_GATEWAY_API_KEY" in out[0].error


def test_request_shape_and_answers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=GOOD)

    c, _ = make(handler)
    out = c.ask("the state", [YN, SC, CH])
    req = seen[0]
    assert req.url == "https://ai-gateway.vercel.sh/v1/evaluate"
    assert req.headers["authorization"] == "Bearer k"
    body = json.loads(req.content)
    assert body["model"] == "typesafe-ai/jev"
    assert body["state"] == "the state"
    qs = body["questions"]
    assert qs["sql"]["type"] == "boolean"
    assert qs["level"]["type"] == "score" and len(qs["level"]["criteria"]) == 4
    assert "0 intern" in qs["level"]["instructions"]
    assert qs["pick"] == {"type": "choice", "criteria": {"a": None, "b": None}, "instructions": "Which?"}
    assert [a.ok for a in out] == [True, True, True]
    assert out[0].value == 0.9
    assert out[1].value == 2 and out[1].confidence == 0.8
    assert out[2].value == "b"
    assert c.usage.requests == 1 and c.usage.reported_input_tokens == 120


def test_score_offset_scale_and_noul_spelling():
    q = Question("s", "score", "x", scale=(1, 5))
    n = Question("n", "yesno", "x")

    def handler(request):
        return httpx.Response(
            200,
            json={"answers": {"s": {"type": "score", "score": 2.2}, "n": {"type": "noul", "noul": 0.25}}},
        )

    c, _ = make(handler)
    a = c.ask("s", [q, n])
    assert a[0].value == 3  # index 2 -> scale 1..5 -> 3
    assert a[1].value == 0.25 and a[1].ok


def test_batching_splits_requests():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200, json={"answers": {k: {"type": "boolean", "probability": 0.5} for k in body["questions"]}}
        )

    qs = [Question(f"q{i}", "yesno", "x" * 400) for i in range(10)]  # ~150 tokens each
    c, _ = make(handler, max_request_tokens=1000)
    out = c.ask("short state", qs)
    assert len(calls) > 1
    assert sum(len(b["questions"]) for b in calls) == 10
    assert [a.id for a in out] == [q.id for q in qs] and all(a.ok for a in out)
    assert c.usage.requests == len(calls)


def test_oversized_state_truncated():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"answers": {"sql": {"type": "boolean", "probability": 1}}})

    c, _ = make(handler)
    c.ask("x" * 400_000, [YN])
    state = seen[0]["state"]
    assert state.endswith(jev_mod.TRUNCATION_MARKER)
    assert jev_mod.est_tokens(state) <= jev_mod.MAX_REQUEST_TOKENS


def test_429_retry_after_then_success():
    n = {"i": 0}

    def handler(request):
        n["i"] += 1
        if n["i"] == 1:
            return httpx.Response(429, headers={"retry-after": "7"})
        if n["i"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, json=GOOD)

    c, sleeps = make(handler)
    out = c.ask("s", [YN, SC, CH])
    assert all(a.ok for a in out)
    assert sleeps == [7.0, 2.0]  # retry-after honored, then exponential backoff (attempt 1)
    assert c.usage.requests == 3


def test_retries_exhausted():
    def handler(request):
        return httpx.Response(429)

    c, sleeps = make(handler, max_retries=2)
    out = c.ask("s", [YN])
    assert not out[0].ok and "429" in out[0].error
    assert c.usage.requests == 3 and len(sleeps) == 2


def test_client_error_not_retried():
    def handler(request):
        return httpx.Response(401, text="bad key")

    c, sleeps = make(handler)
    out = c.ask("s", [YN, CH])
    assert [a.ok for a in out] == [False, False] and "401" in out[0].error
    assert c.usage.requests == 1 and not sleeps


def test_network_error_never_raises():
    def handler(request):
        raise httpx.ConnectError("down")

    c, _ = make(handler, max_retries=1)
    out = c.ask("s", [YN])
    assert not out[0].ok and "network" in out[0].error


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={"answers": "nope"}),
        httpx.Response(200, json={"answers": {}}),
    ],
)
def test_malformed_responses(response):
    c, _ = make(lambda r: response)
    out = c.ask("s", [YN, SC])
    assert [a.ok for a in out] == [False, False]
    assert [a.id for a in out] == ["sql", "level"]


def test_value_validation():
    bad = {
        "answers": {
            "sql": {"type": "boolean", "probability": 1.5},
            "level": {"type": "score", "score": 7},
            "pick": {"type": "choice", "choice": "zzz"},
        }
    }
    c, _ = make(lambda r: httpx.Response(200, json=bad))
    out = c.ask("s", [YN, SC, CH])
    assert [a.ok for a in out] == [False, False, False]


def test_partial_answers_and_unsendable_questions():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"answers": {"sql": {"type": "boolean", "probability": 0.1}}})

    wide = Question("wide", "score", "x", scale=(0, 20))
    nochoice = Question("none", "choice", "x", options=[])
    c, _ = make(handler)
    out = c.ask("s", [wide, YN, CH, nochoice])
    assert [a.ok for a in out] == [False, True, False, False]
    assert set(seen[0]["questions"]) == {"sql", "pick"}


def test_duplicate_ids_get_distinct_keys():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"answers": {k: {"type": "boolean", "probability": 0.4} for k in seen[0]["questions"]}})

    c, _ = make(handler)
    out = c.ask("s", [YN, YN])
    assert len(seen[0]["questions"]) == 2 and all(a.ok for a in out)


def test_from_env(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    assert not JevClient.from_env().available
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "abc")
    c = JevClient.from_env({"timeout_s": 5})
    assert c.available and c.cfg["timeout_s"] == 5 and c.cfg["model"] == "typesafe-ai/jev"


def test_answer_dataclass_default():
    assert Answer("x", ok=False).value is None


# --- remembered answers (pipeline audit, Oct 29 2026) ----------------------


def test_remembered_jev_reuses_an_answer_for_the_same_text(tmp_path):
    from src.tailor.jev import FakeJev, remembered

    fake = FakeJev(lambda state, q: 0.7)
    jev = remembered(fake, tmp_path)
    assert remembered(jev, tmp_path) is jev and remembered(None, tmp_path) is None
    first = jev.ask("resume text", [YN, SC])
    again = jev.ask("resume text", [YN, SC])
    assert [a.value for a in again] == [a.value for a in first] == [0.7, 0.7]
    assert len(fake.calls) == 1
    # Other text, or another question about it, is asked afresh; only what's new goes to Jev.
    jev.ask("changed text", [YN])
    jev.ask("resume text", [YN, Question("other", "yesno", "Is it short?")])
    assert [[q.id for q in qs] for _, qs in fake.calls[1:]] == [["sql"], ["other"]]
    assert (tmp_path / "jev-answers.json").exists()


def test_remembered_jev_never_keeps_a_failed_answer(tmp_path):
    from src.tailor.jev import FakeJev, remembered

    jev = remembered(FakeJev({}), tmp_path)  # unreachable: every answer ok=False
    assert jev.ask("t", [YN])[0].ok is False
    later = remembered(FakeJev({"sql": 0.8}), tmp_path)
    assert later.ask("t", [YN])[0].value == 0.8
