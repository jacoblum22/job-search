"""Turn a tailoring-run transcript (claude -p stream-json) into a readable log.

The post-run review (docs/run-review-task.md) reads this instead of the raw
JSONL, which is mostly repeated context. One line per tool call, the result
underneath (cut to --max-chars), errors and permission denials marked, and
Claude's own text between calls.

    uv run python scripts/transcript_summary.py logs/tailoring/2026-10-20_0139.jsonl > run.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _short(value, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + f" ... [{len(text) - limit} more chars]"


def _call_line(name: str, inp: dict) -> str:
    for key in ("command", "file_path", "pattern", "query", "description", "url"):
        if inp.get(key):
            return f"{name}: {inp[key]}"
    return f"{name}: {json.dumps(inp, ensure_ascii=False)[:200]}"


def _result_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


def summarize(lines: list[str], max_chars: int = 1500) -> str:
    out: list[str] = []
    calls: dict[str, str] = {}
    for line in lines:
        line = line.strip().lstrip("﻿")
        if not line.startswith("{"):
            if line:
                out.append(f"(non-JSON output) {line[:300]}")
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = row.get("type")
        sub = " (subagent)" if row.get("parent_tool_use_id") else ""
        if kind == "system" and row.get("subtype") == "init":
            out.append(f"# Run start: model {row.get('model')}, cwd {row.get('cwd')}")
        elif kind == "assistant":
            for c in row["message"].get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    out.append(f"\nCLAUDE{sub}: {_short(c['text'], max_chars)}")
                elif c.get("type") == "tool_use":
                    calls[c["id"]] = c["name"]
                    out.append(f"\n> CALL{sub} {_call_line(c['name'], c.get('input') or {})}")
                    if c["name"] in ("Write", "Edit") and c.get("input"):
                        body = c["input"].get("content") or c["input"].get("new_string") or ""
                        out.append(f"  content: {_short(body, max_chars)}")
                    elif c["name"] == "Agent":
                        out.append(f"  prompt: {_short((c.get('input') or {}).get('prompt', ''), max_chars)}")
        elif kind == "user":
            content = row.get("message", {}).get("content")
            for c in content if isinstance(content, list) else []:
                if c.get("type") != "tool_result":
                    continue
                text = _result_text(c.get("content"))
                mark = "ERROR" if c.get("is_error") else "result"
                if "Permission to use" in text and "denied" in text:
                    out.append(f"  DENIED: {text.split(' because')[0]}")
                    continue
                out.append(f"  {mark}: {_short(text, max_chars)}")
        elif kind == "result":
            out.append(f"\n# Run end: {row.get('subtype')}, {row.get('num_turns')} turns, "
                       f"${row.get('total_cost_usd') or 0:.2f}, {(row.get('duration_ms') or 0) / 60000:.0f} min")
            for d in row.get("permission_denials") or []:
                out.append(f"- denied {d.get('tool_name')}: {_short(d.get('tool_input'), 300)}")
            out.append(f"\n## Final message\n{row.get('result', '')}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--max-chars", type=int, default=1500, help="cut each result to this many characters")
    args = ap.parse_args()
    text = args.transcript.read_text(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(summarize(text.splitlines(), args.max_chars))


if __name__ == "__main__":
    main()
