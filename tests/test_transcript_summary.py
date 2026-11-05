import json

from scripts.transcript_summary import summarize


def row(**kw):
    return json.dumps(kw)


def test_summary_marks_calls_errors_and_denials():
    lines = [
        row(type="system", subtype="init", model="m", cwd="C:/x"),
        row(type="assistant", message={"content": [
            {"type": "text", "text": "Queueing."},
            {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "uv run python -m src.tailor queue"}},
            {"type": "tool_use", "id": "b", "name": "PowerShell", "input": {"command": "dir"}}]}),
        row(type="user", message={"content": [
            {"type": "tool_result", "tool_use_id": "a", "is_error": True, "content": "error: boom"},
            {"type": "tool_result", "tool_use_id": "b", "content": "Permission to use PowerShell has been denied because of mode. Long text."}]}),
        "not json",
        row(type="result", subtype="success", num_turns=3, total_cost_usd=1.5, duration_ms=120000,
            permission_denials=[{"tool_name": "PowerShell", "tool_input": {"command": "dir"}}], result="digest"),
    ]
    out = summarize(lines)
    assert "> CALL Bash: uv run python -m src.tailor queue" in out
    assert "ERROR: error: boom" in out
    assert "DENIED: Permission to use PowerShell has been denied\n" in out
    assert "(non-JSON output) not json" in out
    assert "3 turns, $1.50, 2 min" in out and out.rstrip().endswith("digest")


def test_long_results_are_cut():
    lines = [row(type="user", message={"content": [
        {"type": "tool_result", "tool_use_id": "a", "content": "x" * 50}]})]
    assert "[40 more chars]" in summarize(lines, max_chars=10)
